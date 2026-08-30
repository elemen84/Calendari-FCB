from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import StandingRow


def snapshot_path(root: Path, competition_key: str, season: str, unit: int) -> Path:
    unit_name = "round" if competition_key == "laliga" else "matchday"
    return root / competition_key / season / f"{unit_name}-{unit:02d}.json"


def load_snapshot(path: Path) -> tuple[StandingRow, ...] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["rows"]
        if not isinstance(rows, list):
            return None
        return tuple(StandingRow(**row) for row in rows)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_snapshot_if_absent(
    path: Path,
    *,
    competition_key: str,
    season: str,
    unit: int,
    rows: tuple[StandingRow, ...],
) -> bool:
    if path.exists():
        return False
    payload: dict[str, Any] = {
        "competition": competition_key,
        "season": season,
        "unit": unit,
        "rows": [row.to_dict() for row in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return True


def latest_snapshot(
    root: Path, competition_key: str, season: str
) -> tuple[StandingRow, ...] | None:
    directory = root / competition_key / season
    if not directory.is_dir():
        return None
    paths = sorted(directory.glob("*.json"))
    for path in reversed(paths):
        rows = load_snapshot(path)
        if rows:
            return rows
    return None
