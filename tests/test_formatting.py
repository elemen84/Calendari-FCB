from __future__ import annotations

from datetime import datetime

from src.calendar.formatting import (
    _standings_text,
    description_for_game,
    display_team_name,
)
from src.calendar.ics import render_ics
from src.models import Game, StandingRow
from src.normalize import source_key


def _laliga_rows() -> tuple[StandingRow, ...]:
    # Nombres societarios tal como llegan del provider/snapshot (intactos en datos).
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


def test_standings_table_header_and_laliga_shape() -> None:
    lines = _standings_text(_laliga_rows())
    assert lines[0] == "Classificació"
    assert lines[1] == " #  Equip                  PJ  G  E  P  DG  Pts"
    body = lines[2:]
    assert len(body) == 20
    assert body[0].startswith(" 1  Deportivo Alavés")
    assert "FC Barcelona" in body[1]
    assert "· PJ" not in "\n".join(lines)
    assert "SAD" not in "\n".join(lines)
    assert "GF" not in lines[1]
    assert "GC" not in lines[1]
    # Orden y stats clave
    assert body[0].split()[0] == "1"
    assert body[1].split()[0] == "2"
    barca = body[1]
    assert "  2  " in barca  # PJ
    assert barca.rstrip().endswith("6")  # Pts
    assert "+7" in barca
    alaves = body[0]
    assert "+4" in alaves
    assert alaves.rstrip().endswith("7")


def test_original_team_names_untouched_on_rows() -> None:
    rows = _laliga_rows()
    assert rows[0].team == "Deportivo Alavés SAD"
    assert rows[2].team == "Real Madrid Club de Fútbol"
    # Presentación normaliza; el modelo no.
    rendered = "\n".join(_standings_text(rows))
    assert "Deportivo Alavés SAD" not in rendered
    assert "Real Madrid" in rendered
    assert rows[0].team == "Deportivo Alavés SAD"


def test_champions_uses_same_renderer() -> None:
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
    lines = _standings_text(rows)
    assert lines[1] == " #  Equip                  PJ  G  E  P  DG  Pts"
    assert lines[2].startswith(" 1  FC Barcelona")
    assert "+5" in lines[2]
    assert lines[3].startswith(" 2  Bayern München")


def test_long_team_name_does_not_break_alignment() -> None:
    long_name = "A" * 40
    lines = _standings_text(
        (
            StandingRow(
                position=1,
                team=long_name,
                played=1,
                points=3,
                won=1,
                drawn=0,
                lost=0,
                goal_difference=1,
            ),
        )
    )
    row = lines[2]
    assert len(row) == len(lines[1])
    assert long_name not in row
    assert row[4:26] == "A" * 22


def test_description_and_ics_escaping_preserve_newlines_and_folding() -> None:
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
    assert "Classificació\n #  Equip" in description
    assert "· PJ" not in description
    assert "SAD" not in description.split("Classificació", 1)[1]
    assert "Local: FC Barcelona" in description

    rendered = render_ics(
        [game],
        {source_key(game): description},
        dtstamp=datetime.fromisoformat("2026-08-29T18:00:00+00:00"),
    )
    assert "DESCRIPTION:" in rendered
    assert "\\n" in rendered  # saltos lógicos escapados, no rotos
    assert "· PJ" not in rendered
    # Folding físico RFC 5545: líneas continuadas empiezan con espacio
    desc_lines = [line for line in rendered.split("\r\n") if line.startswith("DESCRIPTION:")]
    assert len(desc_lines) == 1
    # La DESCRIPTION larga se pliega en continuaciones
    assert any(line.startswith(" ") for line in rendered.split("\r\n"))
