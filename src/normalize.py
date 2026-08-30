from __future__ import annotations

import re
import unicodedata

from src.models import Game


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", without_marks.lower())


def is_barcelona(value: str) -> bool:
    normalized = normalize_text(value)
    if any(token in normalized for token in ("atletic", "femeni", "femenino", "women", "juvenil")):
        return False
    return normalized in {
        "barcelona",
        "fcbarcelona",
        "futbolclubbarcelona",
        "barcafc",
    }


def display_team_name(value: str) -> str:
    return "FC Barcelona" if is_barcelona(value) else value.strip()


def source_key(game: Game) -> str:
    if game.source_game_id:
        identity = game.source_game_id
    else:
        stage = game.round_name or game.phase
        if not stage and game.round_number is not None:
            stage = f"round-{game.round_number}"
        stage = stage or "unknown-stage"
        identity = "|".join(
            (
                normalize_text(stage),
                normalize_text(game.home),
                normalize_text(game.away),
            )
        )
    return ":".join(
        (
            normalize_text(game.competition_key),
            normalize_text(game.season),
            normalize_text(identity),
        )
    )


def event_uid(game: Game) -> str:
    return f"{source_key(game)}@barca-calendar"
