from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.calendar.formatting import description_for_game, title_for_game
from src.calendar.ics import render_ics
from src.models import StandingRow
from src.normalize import source_key
from src.providers.common import SourceDataError, parse_status
from src.providers.laliga import LaLigaProvider
from src.providers.uefa import UEFAProvider
from src.sync import build_calendar, should_sync

from .conftest import config
from .test_providers import FakeClient, UEFAFakeClient, laliga_match, uefa_match


def test_abandoned_maps_to_postponed_not_completed() -> None:
    assert parse_status("Abandoned", "LaLiga status") == "postponed"
    assert parse_status("abandoned", "LaLiga status") == "postponed"
    assert parse_status("ABANDONED", "LaLiga status") == "postponed"


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


def _foreign_match(
    *,
    match_id: int,
    home: str,
    away: str,
    status: str,
    week: int,
    home_score: int | None = None,
    away_score: int | None = None,
) -> dict[str, Any]:
    raw = deepcopy(laliga_match())
    raw["id"] = match_id
    raw["opta_id"] = f"g-{match_id}"
    raw["home_team"] = {"name": home}
    raw["away_team"] = {"name": away}
    raw["status"] = status
    raw["gameweek"] = {"week": week}
    raw["home_score"] = home_score
    raw["away_score"] = away_score
    return raw


def test_foreign_unknown_status_does_not_block_laliga_sync() -> None:
    # Barça lives in week 4 so week-3 completeness is decided only by foreign fixtures.
    barca = deepcopy(laliga_match())
    barca["gameweek"] = {"week": 4}
    barca["status"] = "FullTime"
    barca["home_score"] = 2
    barca["away_score"] = 0

    foreign_unknown = _foreign_match(
        match_id=99,
        home="Sevilla",
        away="Valencia",
        status="TotallyUnknownForeignStatus",
        week=3,
    )
    foreign_completed = _foreign_match(
        match_id=100,
        home="Athletic Club",
        away="Getafe",
        status="FullTime",
        week=3,
        home_score=1,
        away_score=0,
    )
    # Control round: every attributed fixture is terminal.
    control_a = _foreign_match(
        match_id=101,
        home="Osasuna",
        away="Elche",
        status="FullTime",
        week=2,
        home_score=1,
        away_score=1,
    )
    control_b = _foreign_match(
        match_id=102,
        home="Girona",
        away="Mallorca",
        status="Cancelled",
        week=2,
    )

    client = _TeamAwareLaLigaClient(
        team_matches=[barca],
        all_matches=[barca, foreign_unknown, foreign_completed, control_a, control_b],
    )
    result = LaLigaProvider(config(), client).fetch()

    assert len(result.games) == 1
    assert result.games[0].source_game_id == "g-10"
    assert result.games[0].status == "completed"
    assert {game.home for game in result.games} | {game.away for game in result.games} == {
        "FC Barcelona",
        "Real Madrid",
    }
    assert 3 not in result.complete_units
    assert 2 in result.complete_units


def test_abandoned_foreign_match_keeps_round_incomplete_without_blocking() -> None:
    barca = deepcopy(laliga_match())
    barca["gameweek"] = {"week": 5}
    barca["status"] = "FullTime"
    barca["home_score"] = 3
    barca["away_score"] = 1

    foreign_abandoned = _foreign_match(
        match_id=77,
        home="Osasuna",
        away="Elche",
        status="Abandoned",
        week=3,
    )
    peer = _foreign_match(
        match_id=78,
        home="Girona",
        away="Mallorca",
        status="FullTime",
        week=3,
        home_score=2,
        away_score=2,
    )
    control = _foreign_match(
        match_id=79,
        home="Sevilla",
        away="Valencia",
        status="FullTime",
        week=1,
        home_score=0,
        away_score=0,
    )

    client = _TeamAwareLaLigaClient(
        team_matches=[barca],
        all_matches=[barca, foreign_abandoned, peer, control],
    )
    result = LaLigaProvider(config(), client).fetch()
    assert result.games[0].status == "completed"
    assert all("Osasuna" not in f"{g.home}{g.away}" for g in result.games)
    assert 3 not in result.complete_units
    assert 1 in result.complete_units

    rendered = render_ics(result.games, {}, dtstamp=datetime.fromisoformat("2026-09-20T18:00:00+00:00"))
    assert "Osasuna" not in rendered
    assert "Elche" not in rendered
    assert "Ajornat" not in rendered


def test_malformed_foreign_gameweek_blocks_premature_complete_units() -> None:
    barca = deepcopy(laliga_match())
    barca["gameweek"] = {"week": 4}
    barca["status"] = "FullTime"
    barca["home_score"] = 1
    barca["away_score"] = 0

    terminal = _foreign_match(
        match_id=200,
        home="Sevilla",
        away="Valencia",
        status="FullTime",
        week=3,
        home_score=2,
        away_score=1,
    )
    malformed = _foreign_match(
        match_id=201,
        home="Osasuna",
        away="Elche",
        status="PreMatch",
        week=3,
    )
    malformed["gameweek"] = "not-a-dict"

    client = _TeamAwareLaLigaClient(
        team_matches=[barca],
        all_matches=[barca, terminal, malformed],
    )
    result = LaLigaProvider(config(), client).fetch()
    assert result.complete_units == frozenset()
    assert len(result.games) == 1


def test_malformed_gameweek_does_not_queue_snapshot_freeze(tmp_path) -> None:
    barca = deepcopy(laliga_match())
    barca["gameweek"] = {"week": 3}
    barca["status"] = "FullTime"
    barca["home_score"] = 2
    barca["away_score"] = 0
    terminal = _foreign_match(
        match_id=210,
        home="Sevilla",
        away="Valencia",
        status="FullTime",
        week=3,
        home_score=1,
        away_score=0,
    )
    malformed = deepcopy(terminal)
    malformed["id"] = 211
    malformed["opta_id"] = "g-211"
    malformed["home_team"] = {"name": "Osasuna"}
    malformed["away_team"] = {"name": "Elche"}
    malformed["gameweek"] = ["broken"]

    client = _TeamAwareLaLigaClient(
        team_matches=[barca],
        all_matches=[barca, terminal, malformed],
    )
    provider = LaLigaProvider(config(), client)
    fetched = provider.fetch()
    assert 3 not in fetched.complete_units

    rows = (StandingRow(position=1, team="FC Barcelona", played=1, points=3),)
    fetched = type(fetched)(
        competition_key=fetched.competition_key,
        games=fetched.games,
        current_standings=rows,
        completed_units=fetched.completed_units,
        complete_units=fetched.complete_units,
        standings_enabled=True,
        empty_expected=False,
        source_note=fetched.source_note,
    )
    built = build_calendar(
        config(),
        {"laliga": (provider, fetched)},
        cache_root=tmp_path / "cache",
        standings_root=tmp_path / "standings",
        now=datetime.fromisoformat("2026-09-20T21:00:00+02:00"),
    )
    assert built.pending_snapshots == ()
    assert all(game.competition_key == "laliga" for game in built.games)
    assert all("Osasuna" not in f"{game.home}{game.away}" for game in built.games)


def _uefa_foreign(
    *,
    match_id: str,
    home: str,
    away: str,
    status: str,
    matchday: int,
) -> dict[str, Any]:
    raw = deepcopy(uefa_match())
    raw["id"] = match_id
    raw["status"] = status
    raw["homeTeam"] = {"internationalName": home}
    raw["awayTeam"] = {"internationalName": away}
    raw["matchday"] = {"sequenceNumber": str(matchday)}
    return raw


def test_uefa_foreign_unknown_status_does_not_block_sync() -> None:
    barca = deepcopy(uefa_match())
    barca["id"] = "barca-md4"
    barca["matchday"] = {"sequenceNumber": "4"}
    barca["status"] = "FINISHED"
    foreign_unknown = _uefa_foreign(
        match_id="foreign-unknown",
        home="Arsenal",
        away="Inter",
        status="TotallyUnknownForeignStatus",
        matchday=3,
    )
    foreign_done = _uefa_foreign(
        match_id="foreign-done",
        home="Liverpool",
        away="Milan",
        status="FINISHED",
        matchday=3,
    )
    control_a = _uefa_foreign(
        match_id="control-a",
        home="Ajax",
        away="Porto",
        status="FINISHED",
        matchday=2,
    )
    control_b = _uefa_foreign(
        match_id="control-b",
        home="Benfica",
        away="Dortmund",
        status="CANCELLED",
        matchday=2,
    )

    result = UEFAProvider(
        config(),
        UEFAFakeClient([barca, foreign_unknown, foreign_done, control_a, control_b]),
    ).fetch()

    assert len(result.games) == 1
    assert result.games[0].source_game_id == "barca-md4"
    assert 3 not in result.complete_units
    assert 2 in result.complete_units
    rendered = render_ics(result.games, {}, dtstamp=datetime.fromisoformat("2026-09-20T18:00:00+00:00"))
    assert "Arsenal" not in rendered
    assert "Ajornat" not in rendered


def test_uefa_abandoned_foreign_keeps_matchday_incomplete() -> None:
    barca = deepcopy(uefa_match())
    barca["id"] = "barca-md5"
    barca["matchday"] = {"sequenceNumber": "5"}
    barca["status"] = "FINISHED"
    abandoned = _uefa_foreign(
        match_id="abandoned-foreign",
        home="Napoli",
        away="PSG",
        status="Abandoned",
        matchday=3,
    )
    peer = _uefa_foreign(
        match_id="peer-foreign",
        home="Chelsea",
        away="Bayern",
        status="FINISHED",
        matchday=3,
    )
    control = _uefa_foreign(
        match_id="control-md1",
        home="Ajax",
        away="Porto",
        status="FINISHED",
        matchday=1,
    )

    result = UEFAProvider(
        config(),
        UEFAFakeClient([barca, abandoned, peer, control]),
    ).fetch()
    assert result.games[0].source_game_id == "barca-md5"
    assert 3 not in result.complete_units
    assert 1 in result.complete_units


def test_uefa_malformed_matchday_blocks_premature_complete_units() -> None:
    barca = deepcopy(uefa_match())
    barca["id"] = "barca-md4"
    barca["matchday"] = {"sequenceNumber": "4"}
    barca["status"] = "FINISHED"
    terminal = _uefa_foreign(
        match_id="terminal-md3",
        home="Arsenal",
        away="Inter",
        status="FINISHED",
        matchday=3,
    )
    malformed = deepcopy(terminal)
    malformed["id"] = "malformed-md"
    malformed["matchday"] = "not-a-dict"

    result = UEFAProvider(config(), UEFAFakeClient([barca, terminal, malformed])).fetch()
    assert result.complete_units == frozenset()
    assert len(result.games) == 1


def test_uefa_malformed_matchday_does_not_queue_snapshot_freeze(tmp_path) -> None:
    barca = deepcopy(uefa_match())
    barca["id"] = "barca-md3"
    barca["matchday"] = {"sequenceNumber": "3"}
    barca["status"] = "FINISHED"
    terminal = _uefa_foreign(
        match_id="terminal-md3",
        home="Arsenal",
        away="Inter",
        status="FINISHED",
        matchday=3,
    )
    malformed = deepcopy(terminal)
    malformed["id"] = "malformed-md"
    malformed["matchday"] = ["broken"]

    provider = UEFAProvider(config(), UEFAFakeClient([barca, terminal, malformed]))
    fetched = provider.fetch()
    assert fetched.complete_units == frozenset()
    rows = (StandingRow(position=1, team="FC Barcelona", played=1, points=3),)
    fetched = type(fetched)(
        competition_key=fetched.competition_key,
        games=fetched.games,
        current_standings=rows,
        completed_units=fetched.completed_units,
        complete_units=fetched.complete_units,
        standings_enabled=True,
        empty_expected=False,
        source_note=fetched.source_note,
    )
    built = build_calendar(
        config(),
        {"champions": (provider, fetched)},
        cache_root=tmp_path / "cache",
        standings_root=tmp_path / "standings",
        now=datetime.fromisoformat("2026-09-20T21:00:00+02:00"),
    )
    assert built.pending_snapshots == ()
    assert all("Arsenal" not in f"{game.home}{game.away}" for game in built.games)


def test_barca_uefa_abandoned_maps_to_postponed_for_calendar() -> None:
    raw = deepcopy(uefa_match())
    raw["status"] = "Abandoned"
    game = UEFAProvider(config(), UEFAFakeClient([]))._parse_match(raw)
    assert game.status == "postponed"
    assert title_for_game(game).startswith("Ajornat ·")


def test_workflow_dispatch_forces_ics_regeneration_contract() -> None:
    """workflow_dispatch must bypass the 24h gate so ICS always regenerates."""
    workflow = Path(".github/workflows/calendar.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert 'if [ "${{ github.event_name }}" = "workflow_dispatch" ]' in workflow
    assert "python scripts/sync_calendar.py --force" in workflow

    now = datetime.fromisoformat("2026-08-29T12:00:00+02:00")
    state = {"last_successful_sync": "2026-08-28T13:00:00+02:00"}
    assert should_sync(state, now) is False
    assert should_sync(state, now, force=True) is True
