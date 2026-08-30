from __future__ import annotations

from datetime import datetime

from src.config import SeasonConfig


def config() -> SeasonConfig:
    return SeasonConfig(start_year=2026)


def utc_datetime(hour: int = 18) -> datetime:
    return datetime.fromisoformat(f"2026-09-20T{hour:02d}:00:00+00:00")
