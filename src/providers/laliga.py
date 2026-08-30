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

BASE_URL = "https://apim.laliga.com/public-service"
PUBLIC_FRONTEND_KEY = "c13c3a8e2f6b46da9c5c425cf61fab3e"
COMPETITION_KEY = "laliga"
COMPETITION_NAME = "LaLiga"


class LaLigaProvider:
    def __init__(self, config: SeasonConfig, client: JsonClient) -> None:
        self.config = config
        self.client = client
        self.subscription_slug = os.getenv(
            "LALIGA_SUBSCRIPTION_SLUG", f"laliga-easports-{config.start_year}"
        )
        self.api_key = os.getenv("LALIGA_API_KEY") or PUBLIC_FRONTEND_KEY

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Language": "es",
            "Country-Code": "ES",
        }

    def _get_matches(self, *, team_slug: str | None) -> list[dict[str, Any]]:
        all_matches: list[dict[str, Any]] = []
        offset = 0
        page_size = 100
        while True:
            params: dict[str, Any] = {
                "subscriptionSlug": self.subscription_slug,
                "seasonYear": self.config.start_year,
                "limit": page_size,
                "offset": offset,
                "orderField": "date",
                "orderType": "asc",
            }
            if team_slug:
                params["teamSlug"] = team_slug
            payload = as_dict(
                self.client.get_json(
                    f"{BASE_URL}/api/v1/matches", params=params, headers=self.headers
                ),
                "LaLiga matches",
            )
            page = as_list(payload.get("matches"), "LaLiga matches.matches")
            all_matches.extend(page)
            total = int_or_none(payload.get("total"))
            if (
                not page
                or (total is not None and len(all_matches) >= total)
                or len(page) < page_size
            ):
                break
            offset += len(page)
        return all_matches

    def fetch(self) -> ProviderResult:
        team_matches = self._get_matches(team_slug="fc-barcelona")
        if not team_matches:
            raise SourceDataError("LaLiga no ha retornat partits del FC Barcelona")
        all_matches = self._get_matches(team_slug=None)
        if not all_matches:
            raise SourceDataError("LaLiga no ha retornat el calendari complet")

        games = tuple(self._parse_match(item) for item in team_matches)
        if any(not (is_barcelona(game.home) or is_barcelona(game.away)) for game in games):
            raise SourceDataError("LaLiga ha retornat un partit que no és del FC Barcelona")
        round_statuses: dict[int, list[str]] = defaultdict(list)
        for item in all_matches:
            parsed = self._parse_match(item)
            if parsed.round_number is not None:
                round_statuses[parsed.round_number].append(parsed.status)
        complete_units = frozenset(
            unit
            for unit, statuses in round_statuses.items()
            if statuses and all(status in {"completed", "cancelled"} for status in statuses)
        )
        current = self.fetch_standings(None)
        return ProviderResult(
            competition_key=COMPETITION_KEY,
            games=games,
            current_standings=current,
            completed_units=complete_units,
            complete_units=complete_units,
            standings_enabled=True,
            source_note="API pública oficial de LaLiga",
        )

    def fetch_standings(self, week: int | None) -> tuple[StandingRow, ...] | None:
        params: dict[str, Any] = {}
        if week is not None:
            params["week"] = week
        payload = as_dict(
            self.client.get_json(
                f"{BASE_URL}/api/v1/subscriptions/{self.subscription_slug}/standing",
                params=params,
                headers=self.headers,
            ),
            "LaLiga standing",
        )
        rows = payload.get("standings")
        if rows is None:
            return None
        return self._parse_standings(rows)

    def _parse_standings(self, rows: Any) -> tuple[StandingRow, ...]:
        items = as_list(rows, "LaLiga standings")
        parsed: list[StandingRow] = []
        for item in items:
            team = team_name(item.get("team"), "LaLiga standings.team")
            parsed.append(
                StandingRow(
                    position=required_int(item.get("position"), "LaLiga position"),
                    team=team,
                    played=required_int(item.get("played"), "LaLiga played"),
                    points=required_int(item.get("points"), "LaLiga points"),
                    won=int_or_none(item.get("won")),
                    drawn=int_or_none(item.get("drawn")),
                    lost=int_or_none(item.get("lost")),
                    goals_for=int_or_none(item.get("goals_for")),
                    goals_against=int_or_none(item.get("goals_against")),
                    goal_difference=int_or_none(item.get("goal_difference")),
                )
            )
        return tuple(sorted(parsed, key=lambda row: row.position))

    def _parse_match(self, item: dict[str, Any]) -> Game:
        source_id = item.get("opta_id") or item.get("id") or item.get("lde_id")
        home = team_name(item.get("home_team"), "LaLiga home_team")
        away = team_name(item.get("away_team"), "LaLiga away_team")
        if not is_barcelona(home) and not is_barcelona(away):
            # This is valid for the all-matches request used to calculate round completeness.
            pass
        gameweek = item.get("gameweek")
        gameweek_dict = as_dict(gameweek, "LaLiga gameweek") if gameweek is not None else {}
        round_number = int_or_none(gameweek_dict.get("week"))
        date_raw = item.get("date")
        date_value = parse_date(date_raw, "LaLiga date")
        start_datetime = parse_datetime(item.get("time"), "LaLiga time")
        if start_datetime is None and isinstance(date_raw, str) and "T" in date_raw:
            start_datetime = parse_datetime(date_raw, "LaLiga date/time")
        if start_datetime is None and date_value is None:
            raise SourceDataError("LaLiga partit sense data")
        home_score, away_score = score_pair(item)
        venue = item.get("venue")
        venue_name = venue.get("name") if isinstance(venue, dict) else None
        competition = item.get("competition")
        competition_slug = competition.get("slug") if isinstance(competition, dict) else None
        if competition_slug and competition_slug not in {
            "laliga-easports",
            "primera-division",
            "laliga",
        }:
            raise SourceDataError(f"Competición inesperada en LaLiga: {competition_slug}")
        return Game(
            competition_key=COMPETITION_KEY,
            competition_name=COMPETITION_NAME,
            season=self.config.label,
            home=home,
            away=away,
            status=parse_status(item.get("status"), "LaLiga status"),
            source_game_id=str(source_id) if source_id is not None else None,
            round_number=round_number,
            phase="Lliga",
            start_datetime=start_datetime,
            start_date=date_value,
            venue=venue_name if isinstance(venue_name, str) else None,
            home_score=home_score,
            away_score=away_score,
            source_url="https://www.laliga.com/laliga-easports/calendario",
            standings_eligible=True,
        )
