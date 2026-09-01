from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.config import TIMEZONE_NAME

MADRID_TZ = ZoneInfo(TIMEZONE_NAME)
MATCH_STATUSES = frozenset({"scheduled", "live", "completed", "postponed", "cancelled"})


@dataclass(frozen=True, slots=True)
class StandingRow:
    position: int
    team: str
    played: int
    points: int
    won: int | None = None
    drawn: int | None = None
    lost: int | None = None
    goals_for: int | None = None
    goals_against: int | None = None
    goal_difference: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Game:
    competition_key: str
    competition_name: str
    season: str
    home: str
    away: str
    status: str
    source_game_id: str | None = None
    round_number: int | None = None
    phase: str | None = None
    round_name: str | None = None
    leg: str | None = None
    start_datetime: datetime | None = None
    start_date: date | None = None
    time_confirmed: bool = True
    venue: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    source_url: str | None = None
    standings_eligible: bool = False

    def __post_init__(self) -> None:
        if self.status not in MATCH_STATUSES:
            raise ValueError(f"Estat de partit no suportat: {self.status}")
        if self.start_datetime is None and self.start_date is None:
            raise ValueError("Un partit ha de tenir data o data i hora")
        if self.start_datetime is not None and self.start_datetime.tzinfo is None:
            raise ValueError("start_datetime ha de tenir timezone")
        if self.time_confirmed and self.start_datetime is None:
            raise ValueError("Hora confirmada sense start_datetime")
        if not self.time_confirmed and self.start_date is None:
            raise ValueError("Hora no confirmada sense start_date")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.start_datetime is not None:
            value["start_datetime"] = self.start_datetime.isoformat()
        if self.start_date is not None:
            value["start_date"] = self.start_date.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Game:
        start_datetime_raw = value.get("start_datetime")
        start_date_raw = value.get("start_date")
        start_datetime = (
            datetime.fromisoformat(start_datetime_raw)
            if isinstance(start_datetime_raw, str)
            else None
        )
        start_date = (
            date.fromisoformat(start_date_raw) if isinstance(start_date_raw, str) else None
        )
        payload = dict(value)
        payload["start_datetime"] = start_datetime
        payload["start_date"] = start_date
        if "time_confirmed" not in payload:
            # Caches antics sense el camp: només són timed si tenen datetime.
            payload["time_confirmed"] = start_datetime is not None
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    competition_key: str
    games: tuple[Game, ...]
    current_standings: tuple[StandingRow, ...] | None = None
    completed_units: frozenset[int] = frozenset()
    complete_units: frozenset[int] = frozenset()
    standings_enabled: bool = False
    empty_expected: bool = False
    source_note: str | None = None
