from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from src.models import MADRID_TZ
from src.normalize import display_team_name


class SourceDataError(RuntimeError):
    """El payload de la font no és prou complet o coherent per publicar-lo."""


def as_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceDataError(f"Payload incomplet en {context}: s'esperava un objecte")
    return value


def as_list(value: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SourceDataError(f"Payload incomplet en {context}: s'esperava una llista d'objectes")
    return value


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None


def required_int(value: Any, context: str) -> int:
    result = int_or_none(value)
    if result is None:
        raise SourceDataError(f"Camp enter invàlid o absent ({context})")
    return result


def team_name(value: Any, context: str) -> str:
    team = as_dict(value, context)
    for key in ("name", "internationalName", "nickname", "boundname", "displayName"):
        candidate = team.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return display_team_name(candidate)
    translations = team.get("translations")
    if isinstance(translations, dict):
        for key in ("displayOfficialName", "displayName"):
            candidate = translations.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return display_team_name(candidate)
    raise SourceDataError(f"Equip absent ({context})")


def parse_datetime(value: Any, context: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SourceDataError(f"Data/hora invàlida ({context}): {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(MADRID_TZ)


def parse_date(value: Any, context: str) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise SourceDataError(f"Data invàlida ({context}): {value}") from exc


def parse_laliga_style_kickoff(
    item: dict[str, Any], context: str
) -> tuple[datetime | None, date | None, bool]:
    """Parse LaLiga/Copa kickoff using the explicit `time` field as confirmation.

    Official payloads set `time` to the real UTC kickoff when confirmed. When the
    hour is still TBD, `time` is absent/null and `date` is midnight UTC for the
    calendar day only — that midnight must not be treated as a real kickoff.
    """
    date_raw = item.get("date")
    time_raw = item.get("time")
    date_value = parse_date(date_raw, f"{context} date")
    time_confirmed = isinstance(time_raw, str) and bool(time_raw.strip())
    start_datetime = (
        parse_datetime(time_raw, f"{context} time") if time_confirmed else None
    )
    if start_datetime is None and date_value is None:
        raise SourceDataError(f"{context} partit sense data")
    return start_datetime, date_value, time_confirmed


def parse_status(value: Any, context: str) -> str:
    normalized = str(value or "scheduled").strip().lower().replace("_", "").replace("-", "")
    mapping = {
        "prematch": "scheduled",
        "upcoming": "scheduled",
        "scheduled": "scheduled",
        "notstarted": "scheduled",
        "live": "live",
        "inprogress": "live",
        "firsthalf": "live",
        "secondhalf": "live",
        "halftime": "live",
        "finished": "completed",
        "fulltime": "completed",
        "completed": "completed",
        "postponed": "postponed",
        "suspended": "postponed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise SourceDataError(f"Estat desconegut en {context}: {value}") from exc


def score_pair(
    payload: dict[str, Any], home_key: str = "home_score", away_key: str = "away_score"
) -> tuple[int | None, int | None]:
    home = int_or_none(payload.get(home_key))
    away = int_or_none(payload.get(away_key))
    score = payload.get("score")
    if isinstance(score, dict):
        home = home if home is not None else int_or_none(score.get("home"))
        away = away if away is not None else int_or_none(score.get("away"))
        home = home if home is not None else int_or_none(score.get("homeGoals"))
        away = away if away is not None else int_or_none(score.get("awayGoals"))
        regular = score.get("regular")
        if isinstance(regular, dict):
            home = home if home is not None else int_or_none(regular.get("home"))
            away = away if away is not None else int_or_none(regular.get("away"))
    return home, away
