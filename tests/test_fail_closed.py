from __future__ import annotations

from datetime import datetime

import pytest

from src.models import ProviderResult
from src.sync import build_calendar, should_sync

from .conftest import config


def test_sync_gate_waits_24_hours_unless_forced() -> None:
    now = datetime.fromisoformat("2026-08-29T12:00:00+02:00")
    # 23h elapsed → omit
    state = {"last_successful_sync": "2026-08-28T13:00:00+02:00"}
    assert should_sync(state, now) is False
    # manual force → allow even before 24h
    assert should_sync(state, now, force=True) is True
    # exactly 24h elapsed → allow
    assert should_sync({"last_successful_sync": "2026-08-28T12:00:00+02:00"}, now) is True


def test_unexpected_empty_source_raises_before_any_write(tmp_path) -> None:
    result = ProviderResult(competition_key="laliga", games=(), empty_expected=False)
    with pytest.raises(RuntimeError, match="laliga"):
        build_calendar(
            config(),
            {"laliga": (object(), result)},
            cache_root=tmp_path / "cache",
            standings_root=tmp_path / "standings",
            now=datetime.now().astimezone(),
        )
    assert not (tmp_path / "cache").exists()


def test_expected_copa_empty_preserves_existing_cache(tmp_path) -> None:
    from src.models import Game

    cached_game = Game(
        competition_key="copa-del-rey",
        competition_name="Copa del Rei",
        season="2026/2027",
        home="FC Barcelona",
        away="Real Madrid",
        status="scheduled",
        source_game_id="cached-1",
        start_datetime=datetime.fromisoformat("2027-01-06T18:00:00+01:00"),
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "copa-del-rey-2026-2027.json").write_text(
        __import__("json").dumps([cached_game.to_dict()]), encoding="utf-8"
    )
    result = ProviderResult(competition_key="copa-del-rey", games=(), empty_expected=True)
    built = build_calendar(
        config(),
        {"copa-del-rey": (object(), result)},
        cache_root=cache,
        standings_root=tmp_path / "standings",
        now=datetime.now().astimezone(),
    )
    assert built.games == (cached_game,)


def test_unexpected_empty_preserves_last_valid_games(tmp_path) -> None:
    from src.models import Game

    cached_game = Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Real Madrid",
        status="scheduled",
        source_game_id="cached-laliga-1",
        start_datetime=datetime.fromisoformat("2026-10-25T20:00:00+01:00"),
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "laliga-2026-2027.json").write_text(
        __import__("json").dumps([cached_game.to_dict()]), encoding="utf-8"
    )

    built = build_calendar(
        config(),
        {"laliga": (object(), ProviderResult(competition_key="laliga", games=()))},
        cache_root=cache,
        standings_root=tmp_path / "standings",
        now=datetime.now().astimezone(),
    )

    assert built.games == (cached_game,)
