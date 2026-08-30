from __future__ import annotations

from dataclasses import replace

from src.models import Game
from src.normalize import event_uid, source_key

from .conftest import utc_datetime


def game() -> Game:
    return Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Real Madrid",
        status="scheduled",
        source_game_id="g123",
        round_number=12,
        start_datetime=utc_datetime(),
    )


def test_uid_does_not_change_when_time_changes() -> None:
    changed = replace(game(), start_datetime=utc_datetime(20))
    assert source_key(game()) == source_key(changed)
    assert event_uid(game()) == event_uid(changed)


def test_uid_does_not_change_when_stadium_changes() -> None:
    changed = replace(game(), venue="Estadi Olímpic")
    assert event_uid(game()) == event_uid(changed)


def test_uid_does_not_change_when_result_or_status_changes() -> None:
    changed = replace(game(), status="completed", home_score=2, away_score=1)
    assert event_uid(game()) == event_uid(changed)


def test_uefa_knockout_uid_is_stable_when_match_details_change() -> None:
    knockout = replace(
        game(),
        competition_key="champions",
        competition_name="UEFA Champions League",
        source_game_id="uefa-knockout-1",
        phase="Eliminatòria",
        round_name="Quarter-finals",
    )
    changed = replace(
        knockout,
        status="completed",
        home_score=1,
        away_score=0,
        start_datetime=utc_datetime(20),
        venue="Estadi Olímpic",
    )
    assert event_uid(knockout) == event_uid(changed)


def test_fallback_uid_uses_specific_round_before_generic_phase() -> None:
    quarter_final = replace(
        game(),
        source_game_id=None,
        phase="Eliminatòria",
        round_name="Quarter-finals",
    )
    final = replace(quarter_final, round_name="Final")
    assert event_uid(quarter_final) != event_uid(final)


def test_same_source_game_is_deduplicated_by_identity() -> None:
    changed = replace(game(), start_datetime=utc_datetime(19), venue="Nou estadi")
    unique = {source_key(item): item for item in (game(), changed)}
    assert len(unique) == 1
