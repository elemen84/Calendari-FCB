from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

from src.config import SeasonConfig
from src.http_client import JsonClient
from src.models import Game, ProviderResult, StandingRow
from src.normalize import is_barcelona
from src.providers.common import (
    SourceDataError,
    as_dict,
    as_list,
    int_or_none,
    parse_date,
    parse_datetime,
    parse_status,
    required_int,
    score_pair,
    team_name,
)

MATCH_URL = "https://match.uefa.com/v5/matches"
STANDINGS_URL = "https://standings.uefa.com/v1/standings"
COMPETITION_KEY = "champions"
COMPETITION_NAME = "UEFA Champions League"


def _translated_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    translations = value.get("translations")
    if not isinstance(translations, dict):
        return None
    for language in ("EN", "ES"):
        entry = translations.get(language)
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
    return None


def _stage_name(round_data: dict[str, Any]) -> str:
    metadata = round_data.get("metaData")
    if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
        return metadata["name"]
    translated = _translated_name(round_data)
    return translated or ""


def _is_league_phase(round_data: dict[str, Any]) -> bool:
    metadata = round_data.get("metaData")
    metadata_type = metadata.get("type") if isinstance(metadata, dict) else None
    return metadata_type == "GROUP_STANDINGS" or round_data.get("secondaryType") == "GROUP_PHASE"


def _leg_name(value: Any) -> str | None:
    if isinstance(value, dict):
        number = int_or_none(value.get("number"))
        if number == 1:
            return "Anada"
        if number == 2:
            return "Tornada"
        translations = value.get("translations")
        if isinstance(translations, dict):
            names = translations.get("name")
            if isinstance(names, dict):
                for language in ("ES", "EN"):
                    if isinstance(names.get(language), str) and names[language].strip():
                        return names[language].strip()
        return None
    if not isinstance(value, str):
        return None
    normalized = value.lower().replace("_", "-")
    if "first" in normalized or normalized in {"1", "leg1", "ida"}:
        return "Anada"
    if "second" in normalized or normalized in {"2", "leg2", "vuelta"}:
        return "Tornada"
    return value.strip() or None


class UEFAProvider:
    def __init__(self, config: SeasonConfig, client: JsonClient) -> None:
        self.config = config
        self.client = client
        # The current public endpoint works without the browser key. If UEFA starts requiring
        # it, the exposed frontend key can be supplied explicitly without changing the provider.
        self.api_key = os.getenv("UEFA_API_KEY") or None

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _get_matches(self) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        offset = 0
        page_size = 100
        while True:
            payload = self.client.get_json(
                MATCH_URL,
                params={
                    "competitionId": 1,
                    # UEFA uses the season end year; 2026/27 is therefore 2027.
                    "seasonYear": self.config.end_year,
                    "order": "ASC",
                    "offset": offset,
                    "limit": page_size,
                },
                headers=self.headers,
            )
            page = as_list(payload, "UEFA matches")
            matches.extend(page)
            if not page or len(page) < page_size:
                break
            offset += len(page)
        return matches

    def fetch(self) -> ProviderResult:
        all_matches = self._get_matches()
        tournament_matches = [
            item
            for item in all_matches
            if item.get("competitionPhase") == "TOURNAMENT"
            and str(as_dict(item.get("competition"), "UEFA competition").get("id")) == "1"
        ]
        if not tournament_matches:
            raise SourceDataError("UEFA no ha retornat partits de la fase de torneig")
        games = tuple(
            self._parse_match(item)
            for item in tournament_matches
            if is_barcelona(team_name(item.get("homeTeam"), "UEFA homeTeam"))
            or is_barcelona(team_name(item.get("awayTeam"), "UEFA awayTeam"))
        )
        if not games:
            raise SourceDataError("UEFA no ha descobert el FC Barcelona")

        matchday_statuses: dict[int, list[str]] = defaultdict(list)
        for item in tournament_matches:
            parsed = self._parse_match(item)
            matchday = parsed.round_number
            if matchday is not None:
                matchday_statuses[matchday].append(parsed.status)
        complete_units = frozenset(
            unit
            for unit, statuses in matchday_statuses.items()
            if statuses and all(status in {"completed", "cancelled"} for status in statuses)
        )
        return ProviderResult(
            competition_key=COMPETITION_KEY,
            games=games,
            current_standings=self.fetch_standings(),
            completed_units=complete_units,
            complete_units=complete_units,
            standings_enabled=True,
            source_note="API pública oficial UEFA",
        )

    def fetch_standings(self) -> tuple[StandingRow, ...] | None:
        payload = as_list(
            self.client.get_json(
                STANDINGS_URL,
                params={"competitionId": 1, "seasonYear": self.config.end_year},
                headers=self.headers,
            ),
            "UEFA standings",
        )
        if not payload:
            return None
        rows = as_dict(payload[0], "UEFA standings[0]").get("items")
        if rows is None:
            return None
        parsed: list[StandingRow] = []
        for item in as_list(rows, "UEFA standings.items"):
            parsed.append(
                StandingRow(
                    position=required_int(item.get("rank"), "UEFA rank"),
                    team=team_name(item.get("team"), "UEFA standings.team"),
                    played=required_int(item.get("played"), "UEFA played"),
                    points=required_int(item.get("points"), "UEFA points"),
                    won=int_or_none(item.get("won")),
                    drawn=int_or_none(item.get("drawn")),
                    lost=int_or_none(item.get("lost")),
                    goals_for=int_or_none(item.get("goalsFor")),
                    goals_against=int_or_none(item.get("goalsAgainst")),
                    goal_difference=int_or_none(item.get("goalDifference")),
                )
            )
        positions = sorted(row.position for row in parsed)
        if positions != list(range(1, len(parsed) + 1)):
            # Before the first match UEFA can return the full list with rank=1 for every club.
            # That is not a valid classification and must render as unavailable.
            return None
        return tuple(sorted(parsed, key=lambda row: row.position))

    def _parse_match(self, item: dict[str, Any]) -> Game:
        competition = as_dict(item.get("competition"), "UEFA competition")
        if str(competition.get("id")) != "1" or competition.get("code") not in {"UCL", None}:
            raise SourceDataError("Competición inesperada en la respuesta UEFA")
        round_data = as_dict(item.get("round"), "UEFA round")
        kickoff = as_dict(item.get("kickOffTime"), "UEFA kickOffTime")
        date_time_raw = kickoff.get("dateTime")
        # UEFA exposes date and dateTime separately. Only dateTime means a confirmed hour.
        time_confirmed = isinstance(date_time_raw, str) and bool(date_time_raw.strip())
        start_datetime = (
            parse_datetime(date_time_raw, "UEFA dateTime") if time_confirmed else None
        )
        start_date = parse_date(kickoff.get("date") or date_time_raw, "UEFA date")
        if start_datetime is None and start_date is None:
            raise SourceDataError("UEFA partit sense data")
        home = team_name(item.get("homeTeam"), "UEFA homeTeam")
        away = team_name(item.get("awayTeam"), "UEFA awayTeam")
        matchday = as_dict(item.get("matchday"), "UEFA matchday")
        round_number = int_or_none(matchday.get("sequenceNumber"))
        stadium = item.get("stadium")
        stadium_name = None
        if isinstance(stadium, dict):
            for key in ("internationalName", "name"):
                if isinstance(stadium.get(key), str) and stadium[key].strip():
                    stadium_name = stadium[key].strip()
                    break
        home_score, away_score = score_pair(item)
        league_phase = _is_league_phase(round_data)
        return Game(
            competition_key=COMPETITION_KEY,
            competition_name=COMPETITION_NAME,
            season=self.config.label,
            home=home,
            away=away,
            status=parse_status(item.get("status"), "UEFA status"),
            source_game_id=str(item["id"]) if item.get("id") is not None else None,
            round_number=round_number,
            phase="Fase lliga" if league_phase else "Eliminatòria",
            round_name=_stage_name(round_data),
            leg=_leg_name(item.get("leg")),
            start_datetime=start_datetime,
            start_date=start_date,
            time_confirmed=time_confirmed,
            venue=stadium_name,
            home_score=home_score,
            away_score=away_score,
            source_url="https://www.uefa.com/uefachampionsleague/fixtures-results/",
            standings_eligible=league_phase,
        )
