from __future__ import annotations

import os
from typing import Any

from src.config import SeasonConfig
from src.http_client import JsonClient
from src.models import Game, ProviderResult
from src.normalize import is_barcelona
from src.providers.common import (
    SourceDataError,
    as_dict,
    as_list,
    int_or_none,
    parse_laliga_style_kickoff,
    parse_status,
    score_pair,
    team_name,
)

BASE_URL = "https://apim.laliga.com/public-service"
PUBLIC_FRONTEND_KEY = "c13c3a8e2f6b46da9c5c425cf61fab3e"
COMPETITION_KEY = "copa-del-rey"
COMPETITION_NAME = "Copa del Rei"
RFEF_CALENDAR_URL = "https://rfef.es/es/competiciones/copa-del-rey"


class CopaProvider:
    def __init__(self, config: SeasonConfig, client: JsonClient) -> None:
        self.config = config
        self.client = client
        self.api_key = os.getenv("LALIGA_API_KEY") or PUBLIC_FRONTEND_KEY

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Language": "es",
            "Country-Code": "ES",
        }

    def _find_subscription(self) -> dict[str, Any] | None:
        payload = as_dict(
            self.client.get_json(
                f"{BASE_URL}/api/v1/subscriptions",
                params={"competitionSlug": "copa-del-rey"},
                headers=self.headers,
            ),
            "Copa subscriptions",
        )
        subscriptions = as_list(payload.get("subscriptions"), "Copa subscriptions.subscriptions")
        for subscription in subscriptions:
            year = int_or_none(subscription.get("year"))
            season = str(subscription.get("season", ""))
            if year == self.config.start_year or season.startswith(str(self.config.start_year)):
                return subscription
        return None

    def _get_matches(self, slug: str, year: int) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        offset = 0
        page_size = 100
        while True:
            payload = as_dict(
                self.client.get_json(
                    f"{BASE_URL}/api/v1/matches",
                    params={
                        "subscriptionSlug": slug,
                        "seasonYear": year,
                        "teamSlug": "fc-barcelona",
                        "limit": page_size,
                        "offset": offset,
                        "orderField": "date",
                        "orderType": "asc",
                    },
                    headers=self.headers,
                ),
                "Copa matches",
            )
            page = as_list(payload.get("matches"), "Copa matches.matches")
            matches.extend(page)
            total = int_or_none(payload.get("total"))
            if not page or (total is not None and len(matches) >= total) or len(page) < page_size:
                break
            offset += len(page)
        return matches

    def fetch(self) -> ProviderResult:
        subscription = self._find_subscription()
        if subscription is None:
            return ProviderResult(
                competition_key=COMPETITION_KEY,
                games=(),
                empty_expected=True,
                source_note=(
                    "La subscripció pública de Copa 2026/27 encara no està publicada; "
                    f"referència de calendari: {RFEF_CALENDAR_URL}"
                ),
            )
        slug = subscription.get("slug")
        year = int_or_none(subscription.get("year"))
        if not isinstance(slug, str) or year is None:
            raise SourceDataError("La subscripció de Copa no té slug o temporada")
        raw_matches = self._get_matches(slug, year)
        games = tuple(self._parse_match(item) for item in raw_matches)
        if any(not (is_barcelona(game.home) or is_barcelona(game.away)) for game in games):
            raise SourceDataError("Copa ha retornat un partit que no és del FC Barcelona")
        return ProviderResult(
            competition_key=COMPETITION_KEY,
            games=games,
            empty_expected=not games,
            source_note=f"API pública de LaLiga; calendari oficial RFEF: {RFEF_CALENDAR_URL}",
        )

    def _parse_match(self, item: dict[str, Any]) -> Game:
        competition = item.get("competition")
        competition_data = as_dict(competition, "Copa competition")
        if competition_data.get("slug") not in {"copa-del-rey", None}:
            raise SourceDataError("Competición inesperada en Copa")
        source_id = item.get("opta_id") or item.get("id") or item.get("lde_id")
        start_datetime, date_value, time_confirmed = parse_laliga_style_kickoff(item, "Copa")
        gameweek = item.get("gameweek")
        gameweek_data = as_dict(gameweek, "Copa gameweek") if gameweek is not None else {}
        round_name = gameweek_data.get("name") or gameweek_data.get("shortname")
        venue = item.get("venue")
        venue_name = venue.get("name") if isinstance(venue, dict) else None
        home_score, away_score = score_pair(item)
        return Game(
            competition_key=COMPETITION_KEY,
            competition_name=COMPETITION_NAME,
            season=self.config.label,
            home=team_name(item.get("home_team"), "Copa home_team"),
            away=team_name(item.get("away_team"), "Copa away_team"),
            status=parse_status(item.get("status"), "Copa status"),
            source_game_id=str(source_id) if source_id is not None else None,
            round_number=int_or_none(gameweek_data.get("week")),
            round_name=str(round_name).strip() if round_name else None,
            start_datetime=start_datetime,
            start_date=date_value,
            time_confirmed=time_confirmed,
            venue=venue_name if isinstance(venue_name, str) else None,
            home_score=home_score,
            away_score=away_score,
            source_url=RFEF_CALENDAR_URL,
        )
