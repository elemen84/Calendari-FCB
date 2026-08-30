from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from src.models import Game, ProviderResult, StandingRow
from src.normalize import source_key
from src.standings.snapshots import load_snapshot, save_snapshot_if_absent, snapshot_path
from src.sync import build_calendar

from .conftest import config, utc_datetime

ROWS_A = (StandingRow(position=1, team="FC Barcelona", played=1, points=3),)
ROWS_B = (StandingRow(position=1, team="FC Barcelona", played=2, points=6),)


class StandingsProvider:
    def __init__(
        self, current: tuple[StandingRow, ...], historical: tuple[StandingRow, ...] | None = None
    ) -> None:
        self.current = current
        self.historical = historical

    def fetch_standings(self, unit: int | None = None) -> tuple[StandingRow, ...] | None:
        return self.historical if unit is not None and self.historical is not None else self.current


def match(unit: int, *, completed: bool = False, competition: str = "laliga") -> Game:
    return Game(
        competition_key=competition,
        competition_name="LaLiga" if competition == "laliga" else "UEFA Champions League",
        season="2026/2027",
        home="FC Barcelona",
        away="Real Madrid",
        status="completed" if completed else "scheduled",
        source_game_id=f"{competition}-{unit}",
        round_number=unit,
        start_datetime=utc_datetime(),
        standings_eligible=True,
    )


def result(game: Game, rows: tuple[StandingRow, ...], *, complete: bool = False) -> ProviderResult:
    return ProviderResult(
        competition_key=game.competition_key,
        games=(game,),
        current_standings=rows,
        complete_units=frozenset({game.round_number}) if complete else frozenset(),
        completed_units=frozenset({game.round_number}) if complete else frozenset(),
        standings_enabled=True,
    )


def result_many(
    games: tuple[Game, ...],
    rows: tuple[StandingRow, ...],
    *,
    complete_units: frozenset[int] = frozenset(),
) -> ProviderResult:
    return ProviderResult(
        competition_key=games[0].competition_key,
        games=games,
        current_standings=rows,
        complete_units=complete_units,
        completed_units=complete_units,
        standings_enabled=True,
    )


def save_pending(build_result) -> None:
    for path, competition_key, season, unit, rows in build_result.pending_snapshots:
        save_snapshot_if_absent(
            path,
            competition_key=competition_key,
            season=season,
            unit=unit,
            rows=rows,
        )


def build(tmp_path, fetched, provider):
    return build_calendar(
        config(),
        {fetched.competition_key: (provider, fetched)},
        cache_root=tmp_path / "cache",
        standings_root=tmp_path / "standings",
        now=datetime.fromisoformat("2026-08-29T16:00:00+02:00"),
    )


def test_current_updates_for_non_completed_round(tmp_path) -> None:
    provider = StandingsProvider(ROWS_A)
    first = build(tmp_path, result(match(1), ROWS_A), provider)
    provider.current = ROWS_B
    second = build(tmp_path, result(match(1), ROWS_B), provider)
    assert " 1  FC Barcelona            1  -  -  -   -    3" in first.descriptions[
        next(iter(first.descriptions))
    ]
    assert " 1  FC Barcelona            2  -  -  -   -    6" in second.descriptions[
        next(iter(second.descriptions))
    ]


def test_champions_observation_freeze_preserves_md1_while_md2_changes(tmp_path) -> None:
    md1 = replace(match(1, competition="champions", completed=True), phase="Fase lliga")
    md2 = replace(match(2, competition="champions"), phase="Fase lliga")
    provider = StandingsProvider(ROWS_A)

    first = build(
        tmp_path,
        result_many((md1, md2), ROWS_A, complete_units=frozenset({1})),
        provider,
    )
    save_pending(first)

    provider.current = ROWS_B
    second = build(
        tmp_path,
        result_many((md1, md2), ROWS_B, complete_units=frozenset({1})),
        provider,
    )
    assert " 1  FC Barcelona            1  -  -  -   -    3" in second.descriptions[source_key(md1)]
    assert " 1  FC Barcelona            2  -  -  -   -    6" in second.descriptions[source_key(md2)]
    md2_path = snapshot_path(tmp_path / "standings", "champions", "2026/2027", 2)
    assert load_snapshot(md2_path) is None

    third = build(
        tmp_path,
        result_many(
            (md1, replace(md2, status="completed")),
            ROWS_B,
            complete_units=frozenset({1, 2}),
        ),
        provider,
    )
    save_pending(third)
    md1_path = snapshot_path(tmp_path / "standings", "champions", "2026/2027", 1)
    assert load_snapshot(md1_path) == ROWS_A
    assert load_snapshot(md2_path) == ROWS_B

    provider.current = ROWS_A
    fourth = build(
        tmp_path,
        result_many(
            (md1, replace(md2, status="completed")),
            ROWS_A,
            complete_units=frozenset({1, 2}),
        ),
        provider,
    )
    assert load_snapshot(md1_path) == ROWS_A
    assert load_snapshot(md2_path) == ROWS_B
    assert " 1  FC Barcelona            1  -  -  -   -    3" in fourth.descriptions[source_key(md1)]
    assert " 1  FC Barcelona            2  -  -  -   -    6" in fourth.descriptions[source_key(md2)]


def test_completed_round_freezes_snapshot_and_does_not_overwrite(tmp_path) -> None:
    provider = StandingsProvider(ROWS_A, ROWS_A)
    first = build(tmp_path, result(match(1, completed=True), ROWS_A, complete=True), provider)
    path = snapshot_path(tmp_path / "standings", "laliga", "2026/2027", 1)
    save_snapshot_if_absent(path, competition_key="laliga", season="2026/2027", unit=1, rows=ROWS_A)
    provider.current = ROWS_B
    second = build(tmp_path, result(match(1, completed=True), ROWS_B, complete=True), provider)
    assert load_snapshot(path) == ROWS_A
    assert " 1  FC Barcelona            1  -  -  -   -    3" in second.descriptions[
        next(iter(second.descriptions))
    ]
    assert first.games == second.games


def test_future_round_uses_latest_available_snapshot_when_current_missing(tmp_path) -> None:
    path = snapshot_path(tmp_path / "standings", "laliga", "2026/2027", 1)
    save_snapshot_if_absent(path, competition_key="laliga", season="2026/2027", unit=1, rows=ROWS_A)
    future = match(2)
    future = replace(future, start_datetime=utc_datetime(22))
    provider = StandingsProvider(())
    built = build(tmp_path, result(future, ()), provider)
    assert " 1  FC Barcelona            1  -  -  -   -    3" in built.descriptions[
        next(iter(built.descriptions))
    ]


def test_champions_knockout_has_no_standings(tmp_path) -> None:
    knockout = replace(
        match(1, competition="champions"), phase="Eliminatòria", standings_eligible=False
    )
    provider_result = result(knockout, ROWS_A)
    built = build(tmp_path, provider_result, StandingsProvider(ROWS_A))
    description = built.descriptions[next(iter(built.descriptions))]
    assert "Classificació" not in description
    assert "Fase:" in description


@pytest.mark.parametrize(
    ("round_name", "label"),
    (
        ("Knock-out Play-off", "Play-off"),
        ("Round of 16", "Vuitens de final"),
        ("Quarter-finals", "Quarts de final"),
        ("Semi-finals", "Semifinals"),
        ("Final", "Final"),
    ),
)
def test_all_champions_knockout_stages_exclude_standings(tmp_path, round_name, label) -> None:
    knockout = replace(
        match(1, competition="champions"),
        phase="Eliminatòria",
        round_name=round_name,
        standings_eligible=False,
    )
    built = build(tmp_path, result(knockout, ROWS_A), StandingsProvider(ROWS_A))
    description = built.descriptions[source_key(knockout)]
    assert f"Fase: {label}" in description
    assert "Classificació" not in description


def test_copa_never_has_standings(tmp_path) -> None:
    copa = replace(
        match(1, competition="copa-del-rey"),
        competition_name="Copa del Rei",
        standings_eligible=False,
    )
    provider_result = result(copa, ROWS_A)
    built = build(tmp_path, provider_result, StandingsProvider(ROWS_A))
    assert "Classificació" not in built.descriptions[next(iter(built.descriptions))]
