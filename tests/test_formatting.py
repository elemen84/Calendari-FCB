from __future__ import annotations

from datetime import datetime

from src.calendar.formatting import (
    _standings_text,
    description_for_game,
    display_team_name,
)
from src.calendar.ics import render_ics, write_ics
from src.models import Game, ProviderResult, StandingRow
from src.normalize import source_key
from src.sync import build_calendar

from .conftest import config


def _laliga_rows() -> tuple[StandingRow, ...]:
    raw = [
        (1, "Deportivo Alavés SAD", 3, 2, 1, 0, 5, 1, 4, 7),
        (2, "FC Barcelona", 2, 2, 0, 0, 7, 0, 7, 6),
        (3, "Real Madrid Club de Fútbol", 2, 2, 0, 0, 6, 2, 4, 6),
        (4, "Sevilla Fútbol Club SAD", 2, 2, 0, 0, 5, 2, 3, 6),
        (5, "Real Betis Balompié SAD", 3, 2, 0, 1, 4, 5, -1, 6),
        (6, "Club Atlético de Madrid SAD", 2, 1, 1, 0, 4, 2, 2, 4),
        (7, "Club Atlético Osasuna", 2, 1, 1, 0, 2, 1, 1, 4),
        (8, "RCD Espanyol de Barcelona", 2, 1, 1, 0, 2, 1, 1, 4),
        (9, "Getafe Club de Fútbol SAD", 2, 1, 0, 1, 2, 2, 0, 3),
        (10, "Villarreal Club de Fútbol SAD", 2, 1, 0, 1, 3, 3, 0, 3),
        (11, "Real Club Deportivo de A Coruña SAD", 2, 0, 2, 0, 2, 2, 0, 2),
        (12, "Real Racing Club SAD", 2, 0, 2, 0, 2, 2, 0, 2),
        (13, "Rayo Vallecano de Madrid SAD", 2, 0, 1, 1, 2, 3, -1, 1),
        (14, "Real Club Celta de Vigo SAD", 2, 0, 1, 1, 1, 2, -1, 1),
        (15, "Valencia Club de Fútbol SAD", 2, 0, 1, 1, 1, 2, -1, 1),
        (16, "Málaga Club de Fútbol SAD", 2, 0, 1, 1, 1, 3, -2, 1),
        (17, "Levante Unión Deportiva SAD", 2, 0, 1, 1, 1, 3, -2, 1),
        (18, "Elche Club de Fútbol SAD", 2, 0, 0, 2, 1, 4, -3, 0),
        (19, "Athletic Club", 2, 0, 0, 2, 1, 4, -3, 0),
        (20, "Real Sociedad de Fútbol SAD", 2, 0, 0, 2, 0, 4, -4, 0),
    ]
    return tuple(
        StandingRow(
            position=pos,
            team=team,
            played=played,
            won=won,
            drawn=drawn,
            lost=lost,
            goals_for=gf,
            goals_against=ga,
            goal_difference=dg,
            points=pts,
        )
        for pos, team, played, won, drawn, lost, gf, ga, dg, pts in raw
    )


def test_display_team_name_maps_known_and_falls_back() -> None:
    assert display_team_name("Deportivo Alavés SAD") == "Deportivo Alavés"
    assert display_team_name("Real Madrid Club de Fútbol") == "Real Madrid"
    assert display_team_name("Club Atlético de Madrid SAD") == "Atlético de Madrid"
    assert display_team_name("FC Barcelona") == "FC Barcelona"
    assert display_team_name("Equipo Desconocido XYZ") == "Equipo Desconocido XYZ"


def test_standings_vertical_format_laliga() -> None:
    lines = _standings_text(_laliga_rows())
    text = "\n".join(lines)
    assert lines[0] == "Classificació"
    assert "1. Deportivo Alavés — 7 pts" in text
    assert "2. FC Barcelona — 6 pts" in text
    assert "3. Real Madrid — 6 pts" in text
    assert "   3 PJ · 2 G · 1 E · 0 P · +4 DG" in text
    assert "   2 PJ · 2 G · 0 E · 0 P · +7 DG" in text
    assert "#  Equip" not in text
    assert "Pos Equip" not in text
    assert "\u2007" not in text
    assert "SAD" not in text
    assert "· PJ " not in text  # antiguo narrativo "· PJ N"
    assert " PJ · " in text
    assert text.count("—") == 20
    # Línea vacía entre equipos
    assert "\n\n2. FC Barcelona" in text


def test_original_team_names_untouched_on_rows() -> None:
    rows = _laliga_rows()
    assert rows[0].team == "Deportivo Alavés SAD"
    assert rows[2].team == "Real Madrid Club de Fútbol"
    rendered = "\n".join(_standings_text(rows))
    assert "Deportivo Alavés SAD" not in rendered
    assert "Real Madrid" in rendered
    assert rows[0].team == "Deportivo Alavés SAD"


def test_champions_uses_same_vertical_format() -> None:
    rows = (
        StandingRow(
            position=1,
            team="FC Barcelona",
            played=2,
            points=6,
            won=2,
            drawn=0,
            lost=0,
            goal_difference=5,
        ),
        StandingRow(
            position=2,
            team="Bayern München",
            played=2,
            points=6,
            won=2,
            drawn=0,
            lost=0,
            goal_difference=4,
        ),
    )
    text = "\n".join(_standings_text(rows))
    assert "1. FC Barcelona — 6 pts" in text
    assert "   2 PJ · 2 G · 0 E · 0 P · +5 DG" in text
    assert "2. Bayern München — 6 pts" in text
    assert "#  Equip" not in text


def test_description_and_ics_escaping() -> None:
    game = Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Sevilla Fútbol Club SAD",
        status="completed",
        source_game_id="g-fmt",
        round_number=2,
        start_datetime=datetime.fromisoformat("2026-08-29T20:00:00+02:00"),
        home_score=3,
        away_score=0,
        standings_eligible=True,
    )
    description = description_for_game(
        game,
        _laliga_rows(),
        updated_at=datetime.fromisoformat("2026-08-29T20:38:00+02:00"),
    )
    assert "Classificació" in description
    assert "1. Deportivo Alavés — 7 pts" in description
    assert "2. FC Barcelona — 6 pts" in description
    assert "   3 PJ · 2 G · 1 E · 0 P · +4 DG" in description
    assert "#  Equip" not in description
    assert "\u2007" not in description
    assert "SAD" not in description.split("Classificació", 1)[1]
    assert "X-ALT-DESC" not in description

    rendered = render_ics(
        [game],
        {source_key(game): description},
        dtstamp=datetime.fromisoformat("2026-08-29T18:00:00+00:00"),
    )
    assert "DESCRIPTION:" in rendered
    assert "X-ALT-DESC" not in rendered
    assert "\\n" in rendered
    assert "1. Deportivo Alavés — 7 pts" in rendered.replace("\\n", "\n")
    assert "#  Equip" not in rendered
    assert "\u2007" not in rendered
    assert any(line.startswith(" ") for line in rendered.split("\r\n"))


class _PassthroughStandingsProvider:
    def fetch_standings(self, unit: int | None = None) -> tuple[StandingRow, ...] | None:
        return None


def test_production_build_path_writes_vertical_standings(tmp_path) -> None:
    game = Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Rayo Vallecano de Madrid SAD",
        status="scheduled",
        source_game_id="g-rayo-j3",
        round_number=3,
        start_datetime=datetime.fromisoformat("2026-09-14T20:00:00+02:00"),
        standings_eligible=True,
    )
    rows = _laliga_rows()
    assert any("SAD" in row.team for row in rows)
    fetched = ProviderResult(
        competition_key="laliga",
        games=(game,),
        current_standings=rows,
        standings_enabled=True,
    )
    built = build_calendar(
        config(),
        {"laliga": (_PassthroughStandingsProvider(), fetched)},
        cache_root=tmp_path / "cache",
        standings_root=tmp_path / "standings",
        now=datetime.fromisoformat("2026-08-30T12:34:00+02:00"),
    )
    description = built.descriptions[source_key(game)]
    assert "Classificació" in description
    assert "1. Deportivo Alavés — 7 pts" in description
    assert "FC Barcelona" in description
    assert "   2 PJ · 2 G · 0 E · 0 P · +7 DG" in description
    assert "#  Equip" not in description
    assert "Pos Equip" not in description
    assert "\u2007" not in description
    assert "SAD" not in description.split("Classificació", 1)[1]

    ics_path = tmp_path / "barca.ics"
    write_ics(ics_path, built.games, built.descriptions)
    ics = ics_path.read_bytes().decode("utf-8")
    assert "BEGIN:VEVENT" in ics
    assert "DESCRIPTION:" in ics
    assert "X-ALT-DESC" not in ics
    assert "FC Barcelona" in ics
    assert "#  Equip" not in ics
    assert "\u2007" not in ics

    unfolded: list[str] = []
    for line in ics.split("\r\n"):
        if line.startswith(" ") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    desc_line = next(line for line in unfolded if line.startswith("DESCRIPTION:"))
    desc = desc_line.removeprefix("DESCRIPTION:").replace("\\n", "\n")
    assert "1. Deportivo Alavés — 7 pts" in desc
    standings_block = desc.split("Classificació", 1)[1]
    assert "SAD" not in standings_block
    assert "Atlético de Madrid" in standings_block
    assert "6. Atlético de Madrid — 4 pts" in standings_block


def test_champions_league_phase_uses_same_vertical_format(tmp_path) -> None:
    game = Game(
        competition_key="champions",
        competition_name="UEFA Champions League",
        season="2026/2027",
        home="FC Barcelona",
        away="Feyenoord",
        status="scheduled",
        source_game_id="ucl-md1",
        round_number=1,
        phase="Fase lliga",
        start_datetime=datetime.fromisoformat("2026-09-16T21:00:00+02:00"),
        standings_eligible=True,
    )
    rows = (
        StandingRow(
            position=1,
            team="FC Barcelona",
            played=1,
            points=3,
            won=1,
            drawn=0,
            lost=0,
            goal_difference=2,
        ),
    )
    fetched = ProviderResult(
        competition_key="champions",
        games=(game,),
        current_standings=rows,
        standings_enabled=True,
    )
    built = build_calendar(
        config(),
        {"champions": (_PassthroughStandingsProvider(), fetched)},
        cache_root=tmp_path / "cache",
        standings_root=tmp_path / "standings",
        now=datetime.fromisoformat("2026-08-30T12:34:00+02:00"),
    )
    description = built.descriptions[source_key(game)]
    assert "1. FC Barcelona — 3 pts" in description
    assert "   1 PJ · 1 G · 0 E · 0 P · +2 DG" in description
    assert "#  Equip" not in description
