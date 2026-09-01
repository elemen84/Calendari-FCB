from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime

from src.calendar.formatting import description_for_game, title_for_game
from src.calendar.ics import render_ics
from src.models import Game
from src.normalize import event_uid, source_key
from src.providers.copa import CopaProvider
from src.providers.laliga import LaLigaProvider
from src.providers.uefa import UEFAProvider

from .conftest import config
from .test_providers import FakeClient, copa_match, laliga_match, uefa_match


def _confirmed_game() -> Game:
    return Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Villarreal",
        status="scheduled",
        source_game_id="g-tbd-1",
        round_number=12,
        start_datetime=datetime.fromisoformat("2026-11-22T20:00:00+01:00"),
        start_date=date(2026, 11, 22),
        time_confirmed=True,
        standings_eligible=True,
    )


def _tbd_game(*, day: date = date(2026, 11, 22)) -> Game:
    return Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Villarreal",
        status="scheduled",
        source_game_id="g-tbd-1",
        round_number=12,
        start_datetime=None,
        start_date=day,
        time_confirmed=False,
        standings_eligible=True,
    )


def test_case_a_confirmed_time_renders_timed_vevent() -> None:
    game = _confirmed_game()
    description = description_for_game(
        game, None, updated_at=datetime.fromisoformat("2026-08-29T16:00:00+02:00")
    )
    rendered = render_ics(
        [game],
        {source_key(game): description},
        dtstamp=datetime.fromisoformat("2026-08-29T14:00:00+00:00"),
    )
    assert "Horari per confirmar" not in title_for_game(game)
    assert "Horari per confirmar" not in rendered
    assert "Hora del partit encara per confirmar." not in rendered
    assert "DTSTART;TZID=Europe/Madrid:20261122T200000" in rendered
    assert "DTEND;TZID=Europe/Madrid:20261122T221500" in rendered
    assert "VALUE=DATE" not in rendered


def test_case_b_tbd_time_renders_all_day_vevent() -> None:
    game = _tbd_game()
    description = description_for_game(
        game, None, updated_at=datetime.fromisoformat("2026-08-29T16:00:00+02:00")
    )
    rendered = render_ics(
        [game],
        {source_key(game): description},
        dtstamp=datetime.fromisoformat("2026-08-29T14:00:00+00:00"),
    )
    assert title_for_game(game) == "FC Barcelona - Villarreal · Horari per confirmar"
    assert "SUMMARY:FC Barcelona - Villarreal · Horari per confirmar" in rendered
    assert "DTSTART;VALUE=DATE:20261122" in rendered
    assert "DTEND;VALUE=DATE:20261123" in rendered
    assert "Hora del partit encara per confirmar." in description
    assert "Hora del partit encara per confirmar." in rendered
    assert "T020000" not in rendered
    assert "T000000" not in rendered
    assert "TZID=Europe/Madrid" not in rendered.split("BEGIN:VEVENT", 1)[1]


def test_case_c_tbd_to_confirmed_keeps_uid() -> None:
    before = _tbd_game()
    after = _confirmed_game()
    assert event_uid(before) == event_uid(after)
    assert source_key(before) == source_key(after)

    before_ics = render_ics([before], {})
    after_ics = render_ics([after], {})
    assert "DTSTART;VALUE=DATE:20261122" in before_ics
    assert "DTSTART;TZID=Europe/Madrid:20261122T200000" in after_ics
    assert "UID:laliga:20262027:gtbd1@barca-calendar" in before_ics
    assert "UID:laliga:20262027:gtbd1@barca-calendar" in after_ics


def test_case_d_tbd_date_change_keeps_uid() -> None:
    first = _tbd_game(day=date(2026, 9, 15))
    second = _tbd_game(day=date(2026, 9, 16))
    assert event_uid(first) == event_uid(second)

    first_ics = render_ics([first], {})
    second_ics = render_ics([second], {})
    assert "DTSTART;VALUE=DATE:20260915" in first_ics
    assert "DTSTART;VALUE=DATE:20260916" in second_ics
    assert event_uid(first) in first_ics and event_uid(second) in second_ics


def test_case_e_historical_confirmed_matches_unchanged() -> None:
    game = Game(
        competition_key="laliga",
        competition_name="LaLiga",
        season="2026/2027",
        home="FC Barcelona",
        away="Athletic Club",
        status="completed",
        source_game_id="g2650779",
        round_number=1,
        start_datetime=datetime.fromisoformat("2026-08-27T21:00:00+02:00"),
        start_date=date(2026, 8, 27),
        time_confirmed=True,
        home_score=3,
        away_score=0,
        standings_eligible=True,
    )
    rendered = render_ics([game], {})
    assert "DTSTART;TZID=Europe/Madrid:20260827T210000" in rendered
    assert "Horari per confirmar" not in rendered
    assert "VALUE=DATE" not in rendered


def test_laliga_tbd_uses_explicit_time_field_not_midnight_date() -> None:
    # Payload real: FC Barcelona - Getafe, jornada 8, hora encara no publicada.
    raw = {
        "id": 102322,
        "opta_id": "g2650835",
        "date": "2026-10-11T00:00:00+00:00",
        "time": None,
        "status": "PreMatch",
        "home_score": None,
        "away_score": None,
        "competition": {"slug": "primera-division"},
        "home_team": {"name": "Fútbol Club Barcelona", "nickname": "FC Barcelona"},
        "away_team": {"name": "Getafe Club de Fútbol SAD", "nickname": "Getafe CF"},
        "gameweek": {"week": 8, "name": "Jornada 8"},
        "venue": {"name": "Spotify Camp Nou"},
    }
    game = LaLigaProvider(config(), FakeClient({}))._parse_match(raw)
    assert game.time_confirmed is False
    assert game.start_datetime is None
    assert game.start_date == date(2026, 10, 11)
    rendered = render_ics([game], {})
    assert "DTSTART;VALUE=DATE:20261011" in rendered
    assert "T020000" not in rendered
    assert "Horari per confirmar" in rendered


def test_laliga_confirmed_time_field_is_used() -> None:
    game = LaLigaProvider(config(), FakeClient({}))._parse_match(laliga_match())
    assert game.time_confirmed is True
    assert game.start_datetime is not None
    assert game.start_datetime.hour == 20  # 18:00 UTC → 20:00 Europe/Madrid (CEST)


def test_copa_tbd_follows_same_time_field_rule() -> None:
    raw = deepcopy(copa_match())
    raw["date"] = "2027-01-06T00:00:00+00:00"
    raw["time"] = None
    raw["status"] = "PreMatch"
    raw["home_score"] = None
    raw["away_score"] = None
    game = CopaProvider(config(), FakeClient({}))._parse_match(raw)
    assert game.time_confirmed is False
    assert game.start_datetime is None
    assert game.start_date == date(2027, 1, 6)


def test_uefa_date_without_datetime_is_tbd() -> None:
    raw = deepcopy(uefa_match())
    raw["kickOffTime"] = {"date": "2026-09-09"}
    game = UEFAProvider(config(), FakeClient({}))._parse_match(raw)
    assert game.time_confirmed is False
    assert game.start_datetime is None
    assert game.start_date == date(2026, 9, 9)


def test_uefa_datetime_present_is_confirmed() -> None:
    game = UEFAProvider(config(), FakeClient({}))._parse_match(uefa_match())
    assert game.time_confirmed is True
    assert game.start_datetime is not None


def test_postponed_tbd_keeps_status_semantics() -> None:
    game = replace(_tbd_game(), status="postponed")
    rendered = render_ics([game], {})
    assert "STATUS:TENTATIVE" in rendered
    assert "SUMMARY:Ajornat · FC Barcelona - Villarreal · Horari per confirmar" in rendered
    assert "DTSTART;VALUE=DATE:20261122" in rendered


def test_game_roundtrip_preserves_time_confirmed() -> None:
    tbd = _tbd_game()
    restored = Game.from_dict(tbd.to_dict())
    assert restored.time_confirmed is False
    assert restored.start_datetime is None
    assert restored.start_date == date(2026, 11, 22)

    confirmed = _confirmed_game()
    restored_confirmed = Game.from_dict(confirmed.to_dict())
    assert restored_confirmed.time_confirmed is True
