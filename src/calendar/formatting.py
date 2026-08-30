from __future__ import annotations

from datetime import datetime

from src.models import Game, StandingRow

# Nombres societarios → nombres deportivos legibles (solo presentación).
_TEAM_DISPLAY_NAMES: dict[str, str] = {
    "Deportivo Alavés SAD": "Deportivo Alavés",
    "Real Madrid Club de Fútbol": "Real Madrid",
    "Sevilla Fútbol Club SAD": "Sevilla",
    "Real Betis Balompié SAD": "Real Betis",
    "Club Atlético de Madrid SAD": "Atlético de Madrid",
    "Club Atlético Osasuna": "Osasuna",
    "Levante Unión Deportiva SAD": "Levante",
    "Real Racing Club SAD": "Racing",
    "RCD Espanyol de Barcelona": "Espanyol",
    "Getafe Club de Fútbol SAD": "Getafe",
    "Real Sociedad de Fútbol SAD": "Real Sociedad",
    "Real Club Deportivo de A Coruña SAD": "Deportivo",
    "Villarreal Club de Fútbol SAD": "Villarreal",
    "Rayo Vallecano de Madrid SAD": "Rayo Vallecano",
    "Real Club Celta de Vigo SAD": "Celta de Vigo",
    "Valencia Club de Fútbol SAD": "Valencia",
    "Málaga Club de Fútbol SAD": "Málaga",
    "Elche Club de Fútbol SAD": "Elche",
    "Athletic Club": "Athletic Club",
    "FC Barcelona": "FC Barcelona",
}


def display_team_name(name: str) -> str:
    """Nombre deportivo para la clasificación; fallback al original."""
    return _TEAM_DISPLAY_NAMES.get(name, name)


def _stage_label(game: Game) -> str:
    if game.phase == "Fase lliga":
        return "Fase lliga"
    raw = (game.round_name or game.phase or "").strip()
    normalized = raw.lower().replace("·", "").replace("-", " ")
    if any(token in normalized for token in ("league", "lliga")):
        return "Fase lliga"
    if any(
        token in normalized for token in ("round of 16", "last 16", "octavos", "1/8", "vuitens")
    ):
        return "Vuitens de final"
    if "knock out play off" in normalized or "play off" in normalized:
        return "Play-off"
    if any(token in normalized for token in ("quarter", "cuartos", "1/4", "quarts")):
        return "Quarts de final"
    if any(token in normalized for token in ("semi", "semifinal")):
        return "Semifinals"
    if normalized == "final" or normalized.endswith(" final"):
        return "Final"
    if any(token in normalized for token in ("sixteen", "dieciseis", "1/16", "setzens")):
        return "Setzens de final"
    return raw


def _status_label(status: str) -> str:
    return {
        "scheduled": "Partit",
        "live": "En directe",
        "completed": "Finalitzat",
        "postponed": "Ajornat",
        "cancelled": "Cancel·lat",
    }[status]


def _competition_title(game: Game) -> str:
    if game.competition_key == "champions":
        return "Champions League"
    return game.competition_name


def title_for_game(game: Game) -> str:
    title = f"{game.home} - {game.away} · {_competition_title(game)}"
    if game.status == "postponed":
        return f"Ajornat · {title}"
    if game.status == "cancelled":
        return f"Cancel·lat · {title}"
    return title


def _stat(value: int | None) -> str:
    return "-" if value is None else str(value)


def _goal_difference(value: int | None) -> str:
    return "-" if value is None else f"{value:+d}"


def _standings_entry(row: StandingRow) -> list[str]:
    team = display_team_name(row.team)
    return [
        f"{row.position}. {team} — {row.points} pts",
        (
            f"   {row.played} PJ · {_stat(row.won)} G · {_stat(row.drawn)} E · "
            f"{_stat(row.lost)} P · {_goal_difference(row.goal_difference)} DG"
        ),
    ]


def _standings_text(rows: tuple[StandingRow, ...] | None) -> list[str]:
    if not rows:
        return ["Classificació encara no disponible"]
    lines = ["Classificació"]
    for index, row in enumerate(rows):
        if index > 0:
            lines.append("")
        lines.extend(_standings_entry(row))
    return lines


def description_for_game(
    game: Game,
    standings: tuple[StandingRow, ...] | None,
    *,
    updated_at: datetime,
) -> str:
    lines = [f"Competició: {game.competition_name}"]
    if game.competition_key == "laliga":
        lines.append(
            f"Jornada: {game.round_number}"
            if game.round_number is not None
            else "Jornada: encara no disponible"
        )
    elif game.competition_key == "champions":
        lines.append(f"Fase: {_stage_label(game)}")
        if game.round_number is not None and game.standings_eligible:
            lines.append(f"Jornada: {game.round_number}")
    elif game.round_name:
        lines.append(f"Ronda: {_stage_label(game)}")
    if game.leg:
        lines.append(game.leg)
    lines.extend(
        [
            f"Local: {game.home}",
            f"Visitant: {game.away}",
            f"Estat: {_status_label(game.status)}",
        ]
    )
    if game.home_score is not None and game.away_score is not None:
        lines.append(f"Resultat: {game.home_score}-{game.away_score}")
    if game.venue:
        lines.append(f"Estadi: {game.venue}")
    if game.standings_eligible:
        lines.extend(["", *_standings_text(standings)])
    source = {
        "laliga": "LaLiga",
        "champions": "UEFA",
        "copa-del-rey": "RFEF / LaLiga",
    }.get(game.competition_key, game.competition_name)
    lines.extend(
        [
            "",
            f"Actualitzat: {updated_at.strftime('%d/%m/%Y %H:%M')} ({updated_at.tzname()})",
            f"Font: {source}",
        ]
    )
    return "\n".join(lines)
