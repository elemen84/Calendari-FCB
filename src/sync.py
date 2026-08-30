from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from src.calendar.formatting import description_for_game, html_description_for_game
from src.calendar.ics import write_ics
from src.config import SYNC_INTERVAL_HOURS, SeasonConfig
from src.models import Game, ProviderResult, StandingRow
from src.normalize import source_key
from src.standings.snapshots import (
    latest_snapshot,
    load_snapshot,
    save_snapshot_if_absent,
    snapshot_path,
)


class StandingsProvider(Protocol):
    def fetch_standings(self, unit: int | None = None) -> tuple[StandingRow, ...] | None: ...


@dataclass(frozen=True, slots=True)
class CalendarBuild:
    games: tuple[Game, ...]
    descriptions: dict[str, str]
    html_descriptions: dict[str, str]
    provider_results: dict[str, ProviderResult]
    cached_games: dict[str, tuple[Game, ...]]
    pending_snapshots: tuple[tuple[Path, str, str, int, tuple[StandingRow, ...]], ...]


def should_sync(state: dict[str, Any], now: datetime, *, force: bool = False) -> bool:
    if force:
        return True
    raw = state.get("last_successful_sync")
    if not isinstance(raw, str):
        return True
    try:
        previous = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if previous.tzinfo is None:
        return True
    return now - previous.astimezone(now.tzinfo) >= timedelta(hours=SYNC_INTERVAL_HOURS)


def load_sync_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No es pot llegir {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Sync state invàlid: {path}")
    return value


def save_sync_state(path: Path, *, now: datetime, counts: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_successful_sync": now.isoformat(),
        "counts": counts,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _cache_path(cache_root: Path, competition_key: str, season: str) -> Path:
    return cache_root / f"{competition_key}-{season.replace('/', '-')}.json"


def _load_cached_games(path: Path) -> tuple[Game, ...]:
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return ()
        return tuple(Game.from_dict(item) for item in payload if isinstance(item, dict))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ()


def _save_cached_games(path: Path, games: tuple[Game, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [game.to_dict() for game in games]
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _merge_with_cache(current: tuple[Game, ...], cached: tuple[Game, ...]) -> tuple[Game, ...]:
    merged = {source_key(game): game for game in cached}
    merged.update({source_key(game): game for game in current})
    return tuple(sorted(merged.values(), key=lambda game: source_key(game)))


def _provider_standings(
    provider: StandingsProvider, competition_key: str, unit: int | None
) -> tuple[StandingRow, ...] | None:
    if competition_key == "laliga":
        return provider.fetch_standings(unit)
    return provider.fetch_standings()


def _standings_for_game(
    game: Game,
    result: ProviderResult,
    provider: StandingsProvider,
    standings_root: Path,
    pending: list[tuple[Path, str, str, int, tuple[StandingRow, ...]]],
) -> tuple[StandingRow, ...] | None:
    if not game.standings_eligible:
        return None
    unit = game.round_number
    if unit is None:
        return result.current_standings or latest_snapshot(
            standings_root, game.competition_key, game.season
        )
    path = snapshot_path(standings_root, game.competition_key, game.season, unit)
    frozen = load_snapshot(path)
    if unit in result.complete_units:
        if frozen:
            return frozen
        rows = _provider_standings(provider, game.competition_key, unit) or result.current_standings
        if rows:
            pending.append((path, game.competition_key, game.season, unit, rows))
            return rows
        return None
    return result.current_standings or latest_snapshot(
        standings_root, game.competition_key, game.season
    )


def build_calendar(
    config: SeasonConfig,
    providers: dict[str, tuple[Any, ProviderResult]],
    *,
    cache_root: Path,
    standings_root: Path,
    now: datetime,
) -> CalendarBuild:
    all_games: list[Game] = []
    descriptions: dict[str, str] = {}
    html_descriptions: dict[str, str] = {}
    cached_games: dict[str, tuple[Game, ...]] = {}
    pending_snapshots: list[tuple[Path, str, str, int, tuple[StandingRow, ...]]] = []
    finalized_results: dict[str, ProviderResult] = {}

    for competition_key, (provider, fetched) in providers.items():
        cache_file = _cache_path(cache_root, competition_key, f"{config.label}")
        cached = _load_cached_games(cache_file)
        current_games = tuple(fetched.games)
        if fetched.empty_expected:
            selected_games = _merge_with_cache((), cached)
        else:
            selected_games = _merge_with_cache(current_games, cached)
        if not selected_games and not fetched.empty_expected:
            raise RuntimeError(f"La font {competition_key} no ha produït partits vàlids")
        cached_games[competition_key] = selected_games
        finalized_results[competition_key] = ProviderResult(
            competition_key=fetched.competition_key,
            games=selected_games,
            current_standings=fetched.current_standings,
            completed_units=fetched.completed_units,
            complete_units=fetched.complete_units,
            standings_enabled=fetched.standings_enabled,
            empty_expected=fetched.empty_expected,
            source_note=fetched.source_note,
        )
        for game in selected_games:
            key = source_key(game)
            standings = _standings_for_game(
                game,
                finalized_results[competition_key],
                provider,
                standings_root,
                pending_snapshots,
            )
            descriptions[key] = description_for_game(game, standings, updated_at=now)
            html_descriptions[key] = html_description_for_game(
                game, standings, updated_at=now
            )
            all_games.append(game)

    unique = {source_key(game): game for game in all_games}
    return CalendarBuild(
        games=tuple(sorted(unique.values(), key=lambda game: source_key(game))),
        descriptions=descriptions,
        html_descriptions=html_descriptions,
        provider_results=finalized_results,
        cached_games=cached_games,
        pending_snapshots=tuple(pending_snapshots),
    )


def persist_build(
    build: CalendarBuild,
    *,
    config: SeasonConfig,
    cache_root: Path,
    standings_root: Path,
    ics_path: Path,
    state_path: Path,
    now: datetime,
) -> dict[str, int]:
    for competition_key, games in build.cached_games.items():
        if games:
            _save_cached_games(_cache_path(cache_root, competition_key, config.label), games)
    for path, competition_key, season, unit, rows in build.pending_snapshots:
        save_snapshot_if_absent(
            path,
            competition_key=competition_key,
            season=season,
            unit=unit,
            rows=rows,
        )
    write_ics(
        ics_path,
        build.games,
        build.descriptions,
        html_descriptions=build.html_descriptions,
        dtstamp=now,
        duration_minutes=config.match_duration_minutes,
        calendar_name=f"FC Barcelona {config.label}",
    )
    counts = {key: len(result.games) for key, result in build.provider_results.items()}
    save_sync_state(state_path, now=now, counts=counts)
    return counts
