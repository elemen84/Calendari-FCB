from __future__ import annotations

from datetime import datetime

from src.models import Game, StandingRow

# Ancho fijo de la columna Equip (texto plano ICS; 20–24).
_TEAM_WIDTH = 22

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
    """Nombre deportivo para la tabla de clasificación; fallback al original."""
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


# FIGURE SPACE: ancho de dígito; no colapsa como U+0020 en muchos renderers HTML/UI.
FIGURE_SPACE = "\u2007"


def _truncate_team(name: str) -> str:
    if len(name) <= _TEAM_WIDTH:
        return name
    return name[:_TEAM_WIDTH]


def _pad_left(text: str, width: int, *, pad: str) -> str:
    gap = width - len(text)
    return (pad * gap + text) if gap > 0 else text


def _pad_right(text: str, width: int, *, pad: str) -> str:
    gap = width - len(text)
    return (text + pad * gap) if gap > 0 else text


def _cell_int(value: int | None, width: int, *, pad: str) -> str:
    if value is None:
        return _pad_left("-", width, pad=pad)
    return _pad_left(str(value), width, pad=pad)


def _cell_dg(value: int | None, *, pad: str) -> str:
    if value is None:
        return _pad_left("-", 3, pad=pad)
    return _pad_left(f"{value:+d}", 3, pad=pad)


def _standings_header(*, pad: str) -> str:
    return (
        f"{_pad_left('#', 2, pad=pad)}{pad * 2}{_pad_right('Equip', _TEAM_WIDTH, pad=pad)}{pad}"
        f"{_pad_left('PJ', 2, pad=pad)}{pad}{_pad_left('G', 2, pad=pad)}{pad}"
        f"{_pad_left('E', 2, pad=pad)}{pad}{_pad_left('P', 2, pad=pad)}{pad}"
        f"{_pad_left('DG', 3, pad=pad)}{pad}{_pad_left('Pts', 4, pad=pad)}"
    )


def _standings_row(row: StandingRow, *, pad: str) -> str:
    team = _truncate_team(display_team_name(row.team))
    return (
        f"{_pad_left(str(row.position), 2, pad=pad)}{pad * 2}"
        f"{_pad_right(team, _TEAM_WIDTH, pad=pad)}{pad}"
        f"{_pad_left(str(row.played), 2, pad=pad)}{pad}"
        f"{_cell_int(row.won, 2, pad=pad)}{pad}"
        f"{_cell_int(row.drawn, 2, pad=pad)}{pad}"
        f"{_cell_int(row.lost, 2, pad=pad)}{pad}"
        f"{_cell_dg(row.goal_difference, pad=pad)}{pad}"
        f"{_pad_left(str(row.points), 4, pad=pad)}"
    )


def _standings_text(rows: tuple[StandingRow, ...] | None, *, pad: str = FIGURE_SPACE) -> list[str]:
    if not rows:
        return ["Classificació encara no disponible"]
    lines = ["Classificació", _standings_header(pad=pad)]
    lines.extend(_standings_row(row, pad=pad) for row in rows)
    return lines


def _meta_lines(game: Game, *, updated_at: datetime) -> tuple[list[str], list[str]]:
    """Cabecera y pie de DESCRIPTION (antes/después de la clasificación)."""
    header = [f"Competició: {game.competition_name}"]
    if game.competition_key == "laliga":
        header.append(
            f"Jornada: {game.round_number}"
            if game.round_number is not None
            else "Jornada: encara no disponible"
        )
    elif game.competition_key == "champions":
        header.append(f"Fase: {_stage_label(game)}")
        if game.round_number is not None and game.standings_eligible:
            header.append(f"Jornada: {game.round_number}")
    elif game.round_name:
        header.append(f"Ronda: {_stage_label(game)}")
    if game.leg:
        header.append(game.leg)
    header.extend(
        [
            f"Local: {game.home}",
            f"Visitant: {game.away}",
            f"Estat: {_status_label(game.status)}",
        ]
    )
    if game.home_score is not None and game.away_score is not None:
        header.append(f"Resultat: {game.home_score}-{game.away_score}")
    if game.venue:
        header.append(f"Estadi: {game.venue}")
    source = {
        "laliga": "LaLiga",
        "champions": "UEFA",
        "copa-del-rey": "RFEF / LaLiga",
    }.get(game.competition_key, game.competition_name)
    footer = [
        f"Actualitzat: {updated_at.strftime('%d/%m/%Y %H:%M')} ({updated_at.tzname()})",
        f"Font: {source}",
    ]
    return header, footer


def description_for_game(
    game: Game,
    standings: tuple[StandingRow, ...] | None,
    *,
    updated_at: datetime,
) -> str:
    header, footer = _meta_lines(game, updated_at=updated_at)
    lines = list(header)
    if game.standings_eligible:
        lines.extend(["", *_standings_text(standings, pad=FIGURE_SPACE)])
    lines.extend(["", *footer])
    return "\n".join(lines)


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def html_description_for_game(
    game: Game,
    standings: tuple[StandingRow, ...] | None,
    *,
    updated_at: datetime,
) -> str:
    """Alternativa HTML (X-ALT-DESC) con tabla en <pre> monoespaciado.

    Google Calendar ignora X-ALT-DESC; Apple tampoco lo usa de forma fiable.
    Se emite como mejora para clientes tipo Outlook que sí lo respetan.
    """
    header, footer = _meta_lines(game, updated_at=updated_at)
    parts = [
        "<!DOCTYPE html><html><body>",
        "<div>",
        "<br>".join(_html_escape(line) for line in header),
        "</div>",
    ]
    if game.standings_eligible:
        # ASCII en <pre>: la fuente monoespaciada alinea; evitar FIGURE SPACE aquí.
        table_lines = _standings_text(standings, pad=" ")
        table = "\n".join(_html_escape(line) for line in table_lines)
        parts.append(
            '<pre style="font-family:ui-monospace,Menlo,Consolas,monospace;'
            'white-space:pre;margin:0.75em 0;">'
            f"{table}</pre>"
        )
    parts.extend(
        [
            "<div>",
            "<br>".join(_html_escape(line) for line in footer),
            "</div>",
            "</body></html>",
        ]
    )
    return "".join(parts)
