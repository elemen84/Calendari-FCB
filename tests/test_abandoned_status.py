from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.calendar.formatting import description_for_game, title_for_game
from src.calendar.ics import render_ics
from src.normalize import source_key
from src.providers.common import SourceDataError, parse_status
from src.providers.laliga import LaLigaProvider
from src.sync import should_sync

from .conftest import config
from .test_providers import FakeClient, laliga_match


def test_abandoned_maps_to_postponed_not_completed() -> None:
    assert parse_status("Abandoned", "LaLiga status") == "postponed"
    assert parse_status("abandoned", "LaLiga status") == "postponed"
    assert parse_status("ABANDONED", "LaLiga status") != "completed"


def test_unknown_status_remains_fail_closed() -> None:
    with pytest.raises(SourceDataError, match="Estat desconegut en LaLiga status: WeirdState"):
        parse_status("WeirdState", "LaLiga status")


def test_laliga_abandoned_keeps_original_kickoff_without_inventing_score() -> None:
    raw = deepcopy(laliga_match())
    raw["status"] = "Abandoned"
    raw["home_score"] = None
    raw["away_score"] = None
    game = LaLigaProvider(config(), FakeClient({}))._parse_match(raw)

    assert game.status == "postponed"
    assert game.start_datetime == datetime.fromisoformat("2026-09-20T20:00:00+02:00")
    assert game.time_confirmed is True
    assert game.home_score is None
    assert game.away_score is None
    assert title_for_game(game).startswith("Ajornat ·")
    description = description_for_game(
        game, None, updated_at=datetime.fromisoformat("2026-09-20T21:00:00+02:00")
    )
    assert "Estat: Ajornat" in description
    assert "Resultat:" not in description


def test_laliga_abandoned_renders_tentative_ics() -> None:
    raw = deepcopy(laliga_match())
    raw["status"] = "Abandoned"
    game = LaLigaProvider(config(), FakeClient({}))._parse_match(raw)
    rendered = render_ics(
        [game],
        {source_key(game): description_for_game(game, None, updated_at=game.start_datetime)},
        dtstamp=datetime.fromisoformat("2026-09-20T18:00:00+00:00"),
    )
    assert "BEGIN:VCALENDAR" in rendered
    assert "BEGIN:VEVENT" in rendered
    assert "STATUS:TENTATIVE" in rendered
    assert "STATUS:CONFIRMED" not in rendered
    assert "DTSTART;TZID=Europe/Madrid:20260920T200000" in rendered
    assert rendered.endswith("\r\n")


def test_barca_unknown_status_still_fails_closed() -> None:
    raw = deepcopy(laliga_match())
    raw["status"] = "MysteriousOfficialState"
    with pytest.raises(SourceDataError, match="Estat desconegut en LaLiga status"):
        LaLigaProvider(config(), FakeClient({}))._parse_match(raw)


class _TeamAwareLaLigaClient:
    """Returns Barça fixtures for teamSlug and a wider slate otherwise."""

    def __init__(self, team_matches: list[dict[str, Any]], all_matches: list[dict[str, Any]]) -> None:
        self.team_matches = team_matches
        self.all_matches = all_matches

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if "standing" in url:
            return {"standings": []}
        if "matches" in url:
            assert params is not None
            matches = self.team_matches if params.get("teamSlug") else self.all_matches
            return {"matches": matches, "total": len(matches)}
        raise AssertionError(f"URL inesperada: {url}")


def test_foreign_unknown_status_does_not_block_laliga_sync() -> None:
    barca = deepcopy(laliga_match())
    foreign = deepcopy(laliga_match())
    foreign["id"] = 99
    foreign["opta_id"] = "g-99"
    foreign["home_team"] = {"name": "Sevilla"}
    foreign["away_team"] = {"name": "Valencia"}
    foreign["status"] = "TotallyUnknownForeignStatus"
    foreign["gameweek"] = {"week": 3}

    other_completed = deepcopy(foreign)
    other_completed["id"] = 100
    other_completed["opta_id"] = "g-100"
    other_completed["home_team"] = {"name": "Athletic Club"}
    other_completed["away_team"] = {"name": "Getafe"}
    other_completed["status"] = "FullTime"
    other_completed["home_score"] = 1
    other_completed["away_score"] = 0

    client = _TeamAwareLaLigaClient(
        team_matches=[barca],
        all_matches=[barca, foreign, other_completed],
    )
    result = LaLigaProvider(config(), client).fetch()

    assert len(result.games) == 1
    assert result.games[0].source_game_id == "g-10"
    assert result.games[0].status == "scheduled"
    # Round 3 has an unknown foreign status → must stay incomplete.
    assert 3 not in result.complete_units


def test_abandoned_foreign_match_keeps_round_incomplete_without_blocking() -> None:
    barca = deepcopy(laliga_match())
    foreign_abandoned = deepcopy(laliga_match())
    foreign_abandoned["id"] = 77
    foreign_abandoned["opta_id"] = "g-77"
    foreign_abandoned["home_team"] = {"name": "Osasuna"}
    foreign_abandoned["away_team"] = {"name": "Elche"}
    foreign_abandoned["status"] = "Abandoned"
    foreign_abandoned["gameweek"] = {"week": 3}

    peer = deepcopy(foreign_abandoned)
    peer["id"] = 78
    peer["opta_id"] = "g-78"
    peer["home_team"] = {"name": "Girona"}
    peer["away_team"] = {"name": "Mallorca"}
    peer["status"] = "FullTime"
    peer["home_score"] = 2
    peer["away_score"] = 2

    client = _TeamAwareLaLigaClient(
        team_matches=[barca],
        all_matches=[barca, foreign_abandoned, peer],
    )
    result = LaLigaProvider(config(), client).fetch()
    assert result.games[0].status == "scheduled"
    assert 3 not in result.complete_units


def test_workflow_dispatch_forces_ics_regeneration_contract() -> None:
    """workflow_dispatch must bypass the 24h gate so ICS always regenerates."""
    workflow = Path(".github/workflows/calendar.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "python scripts/sync_calendar.py --force" in workflow
    assert 'github.event_name" = "workflow_dispatch"' in workflow or (
        "github.event_name" in workflow and "workflow_dispatch" in workflow and "--force" in workflow
    )

    now = datetime.fromisoformat("2026-08-29T12:00:00+02:00")
    state = {"last_successful_sync": "2026-08-28T13:00:00+02:00"}
    assert should_sync(state, now) is False
    assert should_sync(state, now, force=True) is True
