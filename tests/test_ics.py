from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.calendar.formatting import description_for_game
from src.calendar.ics import render_ics
from src.models import Game, StandingRow
from src.normalize import source_key


def game(status: str = "scheduled") -> Game:
    return Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Real, Madrid",
        status=status,
        source_game_id="g-1",
        round_number=12,
        start_datetime=datetime.fromisoformat("2026-11-22T20:00:00+01:00"),
        venue="Estadi; Olímpic",
        home_score=2 if status == "completed" else None,
        away_score=1 if status == "completed" else None,
        standings_eligible=True,
    )


def test_ics_has_catalan_labels_timezone_uid_dtstamp_and_escaping() -> None:
    item = game("completed")
    rows = (
        StandingRow(
            position=1,
            team="FC Barcelona",
            played=12,
            points=30,
            won=10,
            drawn=0,
            lost=2,
            goal_difference=20,
        ),
    )
    description = description_for_game(
        item,
        rows,
        updated_at=datetime.fromisoformat("2026-08-29T16:00:00+02:00"),
    )
    key = source_key(item)
    rendered = render_ics(
        [item],
        {key: description},
        dtstamp=datetime.fromisoformat("2026-08-29T14:00:00+00:00"),
        calendar_name="FC Barcelona 2026/2027",
    )
    assert "X-WR-CALNAME:FC Barcelona 2026/2027" in rendered
    assert "X-WR-TIMEZONE:Europe/Madrid" in rendered
    assert "DTSTAMP:20260829T140000Z" in rendered
    assert "UID:laliga:20262027:g1@barca-calendar" in rendered
    assert "Competició: LaLiga" in rendered
    assert "Classificació" in rendered
    unfolded: list[str] = []
    for line in rendered.split("\r\n"):
        if line.startswith(" ") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    desc = next(line for line in unfolded if line.startswith("DESCRIPTION:")).removeprefix(
        "DESCRIPTION:"
    ).replace("\\n", "\n")
    assert "1. FC Barcelona — 30 pts" in desc
    assert "   12 PJ · 10 G · 0 E · 2 P · +20 DG" in desc
    assert "#  Equip" not in rendered
    assert "\u2007" not in rendered
    assert "X-ALT-DESC" not in rendered
    assert "SUMMARY:FC Barcelona - Real\\, Madrid" in rendered
    assert "LOCATION:Estadi\\; Olímpic" in rendered
    assert "DTSTART;TZID=Europe/Madrid:20261122T200000" in rendered
    assert "DTEND;TZID=Europe/Madrid:20261122T221500" in rendered


def test_postponed_and_cancelled_have_ics_status() -> None:
    postponed = game("postponed")
    cancelled = replace(game("scheduled"), source_game_id="g-2", status="cancelled")
    rendered = render_ics(
        [postponed, cancelled], {}, dtstamp=datetime.fromisoformat("2026-08-29T14:00:00+00:00")
    )
    assert "STATUS:TENTATIVE" in rendered
    assert "STATUS:CANCELLED" in rendered
    assert "Ajornat" in rendered
    assert "Cancel·lat" in rendered


def test_duplicate_source_games_render_once() -> None:
    rendered = render_ics([game(), replace(game(), venue="Un altre estadi")], {})
    assert rendered.count("BEGIN:VEVENT") == 1
