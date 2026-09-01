from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from src.providers.common import SourceDataError
from src.providers.copa import CopaProvider
from src.providers.laliga import LaLigaProvider
from src.providers.uefa import UEFAProvider

from .conftest import config


class FakeClient:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        key = url.rsplit("/", 1)[-1]
        if "subscriptions" in url and url.endswith("subscriptions"):
            return self.responses["subscriptions"]
        if "standing" in url:
            return self.responses["standing"]
        if "matches" in url:
            return self.responses.get("matches", {"matches": [], "total": 0})
        return self.responses[key]


class UEFAFakeClient:
    def __init__(self, matches: list[dict[str, Any]]) -> None:
        self.matches = matches
        self.match_offsets: list[int] = []

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if url.endswith("/matches"):
            assert params is not None
            offset = int(params["offset"])
            limit = int(params["limit"])
            self.match_offsets.append(offset)
            return self.matches[offset : offset + limit]
        if url.endswith("/standings"):
            return []
        raise AssertionError(f"URL inesperada: {url}")


def laliga_match() -> dict[str, Any]:
    return {
        "id": 10,
        "opta_id": "g-10",
        "date": "2026-09-20T18:00:00+00:00",
        "time": "2026-09-20T18:00:00+00:00",
        "status": "PreMatch",
        "home_score": None,
        "away_score": None,
        "competition": {"slug": "laliga-easports"},
        "home_team": {"name": "Fútbol Club Barcelona"},
        "away_team": {"name": "Real Madrid"},
        "gameweek": {"week": 3},
        "venue": {"name": "Spotify Camp Nou"},
    }


def uefa_match() -> dict[str, Any]:
    return {
        "id": "ucl-10",
        "status": "UPCOMING",
        "seasonYear": "2027",
        "competitionPhase": "TOURNAMENT",
        "competition": {"id": "1", "code": "UCL"},
        "kickOffTime": {"date": "2026-09-09", "dateTime": "2026-09-09T16:45:00Z"},
        "homeTeam": {"internationalName": "Barcelona"},
        "awayTeam": {"internationalName": "Feyenoord"},
        "round": {
            "metaData": {"name": "League Phase", "type": "GROUP_STANDINGS"},
            "secondaryType": "GROUP_PHASE",
        },
        "matchday": {"sequenceNumber": "1"},
        "stadium": {"internationalName": "Estadi Olímpic"},
        "score": None,
        "leg": None,
    }


def copa_match() -> dict[str, Any]:
    return {
        "id": 30,
        "opta_id": "cup-30",
        "date": "2027-01-06T18:00:00+00:00",
        "time": "2027-01-06T18:00:00+00:00",
        "status": "FullTime",
        "home_score": 2,
        "away_score": 3,
        "competition": {"slug": "copa-del-rey"},
        "home_team": {"name": "Real Sociedad"},
        "away_team": {"name": "FC Barcelona"},
        "gameweek": {"week": 7, "name": "Cuartos de final"},
        "venue": {"name": "Reale Arena"},
    }


def uefa_knockout_match(stage: str, identifier: str, leg: int | None) -> dict[str, Any]:
    raw = deepcopy(uefa_match())
    raw["id"] = identifier
    raw["round"] = {"metaData": {"name": stage, "type": "KNOCK_OUT"}}
    raw["matchday"] = {"sequenceNumber": "9"}
    raw["kickOffTime"] = {"dateTime": "2027-02-10T20:00:00Z"}
    raw["homeTeam"] = {"internationalName": "Barcelona"}
    raw["awayTeam"] = {"internationalName": f"Opponent {identifier}"}
    raw["leg"] = {"number": leg} if leg is not None else None
    return raw


def test_laliga_parse_has_dynamic_identity_and_fields() -> None:
    provider = LaLigaProvider(config(), FakeClient({}))
    game = provider._parse_match(laliga_match())
    assert game.source_game_id == "g-10"
    assert game.home == "FC Barcelona"
    assert game.round_number == 3
    assert game.venue == "Spotify Camp Nou"
    assert game.status == "scheduled"
    assert game.time_confirmed is True


def test_laliga_missing_time_is_not_parsed_from_midnight_date() -> None:
    raw = deepcopy(laliga_match())
    raw["date"] = "2026-10-11T00:00:00+00:00"
    raw["time"] = None
    game = LaLigaProvider(config(), FakeClient({}))._parse_match(raw)
    assert game.time_confirmed is False
    assert game.start_datetime is None
    assert game.start_date.isoformat() == "2026-10-11"


def test_champions_parse_league_phase_and_matchday() -> None:
    provider = UEFAProvider(config(), FakeClient({}))
    game = provider._parse_match(uefa_match())
    assert game.source_game_id == "ucl-10"
    assert game.round_number == 1
    assert game.phase == "Fase lliga"
    assert game.standings_eligible is True


def test_champions_parse_two_leg_round() -> None:
    raw = uefa_match()
    raw["round"] = {"metaData": {"name": "Round of 16", "type": "KNOCK_OUT"}}
    raw["matchday"] = {"sequenceNumber": "1"}
    raw["leg"] = {"number": 1, "translations": {"name": {"EN": "1st leg"}}}
    game = UEFAProvider(config(), FakeClient({}))._parse_match(raw)
    assert game.round_name == "Round of 16"
    assert game.leg == "Anada"
    assert game.standings_eligible is False


def test_champions_discovers_all_phases_without_an_eight_match_limit() -> None:
    league_phase = []
    for matchday in range(1, 9):
        raw = deepcopy(uefa_match())
        raw["id"] = f"league-{matchday}"
        raw["matchday"] = {"sequenceNumber": str(matchday)}
        raw["kickOffTime"] = {"dateTime": f"2026-09-{8 + matchday:02d}T16:45:00Z"}
        league_phase.append(raw)

    knockout = [
        uefa_knockout_match("Knock-out Play-off", "playoff-1", 1),
        uefa_knockout_match("Knock-out Play-off", "playoff-2", 2),
        uefa_knockout_match("Round of 16", "round16-1", 1),
        uefa_knockout_match("Round of 16", "round16-2", 2),
        uefa_knockout_match("Quarter-finals", "quarter-1", 1),
        uefa_knockout_match("Quarter-finals", "quarter-2", 2),
        uefa_knockout_match("Semi-finals", "semi-1", 1),
        uefa_knockout_match("Semi-finals", "semi-2", 2),
        uefa_knockout_match("Final", "final", None),
    ]
    unrelated = []
    for index in range(100):
        raw = deepcopy(uefa_match())
        raw["id"] = f"unrelated-{index}"
        raw["homeTeam"] = {"internationalName": f"Club {index}"}
        raw["awayTeam"] = {"internationalName": f"Club {index + 1}"}
        unrelated.append(raw)

    client = UEFAFakeClient(league_phase + knockout + unrelated)
    result = UEFAProvider(config(), client).fetch()

    assert len(result.games) == 17
    assert {game.source_game_id for game in result.games} == {
        *(f"league-{matchday}" for matchday in range(1, 9)),
        "playoff-1",
        "playoff-2",
        "round16-1",
        "round16-2",
        "quarter-1",
        "quarter-2",
        "semi-1",
        "semi-2",
        "final",
    }
    assert {game.round_name for game in result.games} == {
        "League Phase",
        "Knock-out Play-off",
        "Round of 16",
        "Quarter-finals",
        "Semi-finals",
        "Final",
    }
    assert client.match_offsets == [0, 100]


def test_laliga_empty_team_source_is_unexpected() -> None:
    with pytest.raises(SourceDataError, match="LaLiga"):
        LaLigaProvider(config(), FakeClient({})).fetch()


def test_laliga_rejects_non_barcelona_from_team_endpoint() -> None:
    foreign_match = deepcopy(laliga_match())
    foreign_match["home_team"] = {"name": "Real Madrid"}
    foreign_match["away_team"] = {"name": "Athletic Club"}
    provider = LaLigaProvider(config(), FakeClient({}))
    provider._get_matches = lambda team_slug: [foreign_match]  # type: ignore[method-assign]
    with pytest.raises(SourceDataError, match="FC Barcelona"):
        provider.fetch()


def test_champions_empty_source_is_unexpected() -> None:
    with pytest.raises(SourceDataError, match="UEFA"):
        UEFAProvider(config(), UEFAFakeClient([])).fetch()


def test_copa_parse_round_without_standings() -> None:
    provider = CopaProvider(config(), FakeClient({}))
    game = provider._parse_match(copa_match())
    assert game.round_name == "Cuartos de final"
    assert game.status == "completed"
    assert game.standings_eligible is False


def test_copa_missing_target_subscription_is_expected_empty() -> None:
    client = FakeClient({"subscriptions": {"subscriptions": [], "total": 0}})
    result = CopaProvider(config(), client).fetch()
    assert result.games == ()
    assert result.empty_expected is True


def test_copa_discovers_published_rounds_without_a_fixed_count() -> None:
    final = deepcopy(copa_match())
    final["id"] = 31
    final["opta_id"] = "cup-31"
    final["gameweek"] = {"week": 10, "name": "Final"}
    client = FakeClient(
        {
            "subscriptions": {
                "subscriptions": [
                    {"slug": "copa-del-rey-2026", "year": 2026, "season": "2026-2027"}
                ],
                "total": 1,
            },
            "matches": {"matches": [copa_match(), final], "total": 2},
        }
    )

    result = CopaProvider(config(), client).fetch()

    assert len(result.games) == 2
    assert {game.round_name for game in result.games} == {"Cuartos de final", "Final"}
