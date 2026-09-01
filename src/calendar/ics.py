from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.calendar.formatting import title_for_game
from src.config import DEFAULT_MATCH_DURATION_MINUTES, TIMEZONE_NAME
from src.models import MADRID_TZ, Game
from src.normalize import event_uid, source_key


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in line:
        candidate = current + character
        if len(candidate.encode("utf-8")) > 75 and current:
            chunks.append(current)
            current = " " + character
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def _datetime_value(value: datetime) -> str:
    return value.astimezone(MADRID_TZ).strftime("%Y%m%dT%H%M%S")


def render_ics(
    games: list[Game] | tuple[Game, ...],
    descriptions: dict[str, str],
    *,
    dtstamp: datetime | None = None,
    duration_minutes: int = DEFAULT_MATCH_DURATION_MINUTES,
    calendar_name: str = "FC Barcelona 2026/2027",
) -> str:
    stamp = (dtstamp or datetime.now(UTC)).astimezone(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//FC Barcelona Calendar//CA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{calendar_name}",
        f"X-WR-TIMEZONE:{TIMEZONE_NAME}",
    ]
    unique_games: dict[str, Game] = {}
    for game in games:
        unique_games.setdefault(source_key(game), game)
    for game in sorted(
        unique_games.values(),
        key=lambda item: (
            item.start_date
            or (item.start_datetime.date() if item.start_datetime else datetime.max.date()),
            source_key(item),
        ),
    ):
        key = source_key(game)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event_uid(game)}",
                f"DTSTAMP:{stamp.strftime('%Y%m%dT%H%M%SZ')}",
                f"SUMMARY:{_escape(title_for_game(game))}",
                f"DESCRIPTION:{_escape(descriptions.get(key, ''))}",
                "STATUS:"
                + (
                    "CANCELLED"
                    if game.status == "cancelled"
                    else "TENTATIVE"
                    if game.status == "postponed"
                    else "CONFIRMED"
                ),
            ]
        )
        if game.venue:
            lines.append(f"LOCATION:{_escape(game.venue)}")
        if game.time_confirmed and game.start_datetime is not None:
            start = game.start_datetime.astimezone(MADRID_TZ)
            end = start + timedelta(minutes=duration_minutes)
            lines.append(f"DTSTART;TZID={TIMEZONE_NAME}:{_datetime_value(start)}")
            lines.append(f"DTEND;TZID={TIMEZONE_NAME}:{_datetime_value(end)}")
        else:
            day = game.start_date or (
                game.start_datetime.astimezone(MADRID_TZ).date()
                if game.start_datetime is not None
                else None
            )
            assert day is not None
            lines.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
            lines.append(f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def write_ics(
    path: Path,
    games: list[Game] | tuple[Game, ...],
    descriptions: dict[str, str],
    *,
    dtstamp: datetime | None = None,
    duration_minutes: int = DEFAULT_MATCH_DURATION_MINUTES,
    calendar_name: str = "FC Barcelona 2026/2027",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_ics(
            games,
            descriptions,
            dtstamp=dtstamp,
            duration_minutes=duration_minutes,
            calendar_name=calendar_name,
        ),
        encoding="utf-8",
    )
