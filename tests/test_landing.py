from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_landing_has_three_competitions_and_requested_copy() -> None:
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    assert "Calendari del Barça 2026/2027" in html
    assert "LaLiga" in html
    assert "UEFA Champions League" in html
    assert "Copa del Rei" in html
    assert "SUBSCRIU-TE AL CALENDARI" in html
    assert "Des d'un ordinador, obre Google Calendar." in html
    assert "Des d'URL" in html
    assert "Apple Calendar" in html
    assert "Google Calendar" in html
    assert "Actualització automàtica cada 24 hores." in html
    assert "03 · ALTRES" not in html
    assert "other-link" not in html
    assert "OBRE AMB EL TEU CALENDARI" not in html
    assert html.count("<h3>Altres calendaris</h3>") == 0


def test_landing_uses_webcal_and_no_download_cta() -> None:
    app = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    assert 'replace(/^https?:/i, "webcal:")' in app
    assert "calendar/r?cid" not in app
    assert "download" not in html.lower()
    assert "./styles.css" in html
    assert "./app.js" in html
    assert "./favicon.svg" in html


def test_landing_has_subpath_safe_asset_and_responsive_structure() -> None:
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assets_readme = (ROOT / "public" / "assets" / "README.md").read_text(encoding="utf-8")
    shield = ROOT / "public" / "assets" / "barca-shield.png"
    assert "new URL(FEED_PATH, window.location.href)" in (ROOT / "public" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "repeat(3" in css
    assert "max-width: 900px" in css
    assert "max-width: 640px" in css
    assert "barca-shield.png" in assets_readme
    assert shield.is_file()
    assert "./assets/barca-shield.png" in html
    assert "FC BARCELONA" in html


def test_landing_uses_only_verified_competition_assets() -> None:
    html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assets = ROOT / "public" / "assets" / "competitions"

    assert './assets/competitions/laliga.png' in html
    assert './assets/competitions/champions-league.svg' in html
    assert 'alt=""' in html
    assert (assets / "laliga.png").is_file()
    assert (assets / "champions-league.svg").is_file()
    assert "card-number" not in html
    assert "card-number" not in css
    assert ".hero::after" not in css
    assert ".competition-card::before" not in css


def test_workflow_does_not_trigger_frontend_deploy_for_ics_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "calendar.yml").read_text(encoding="utf-8")
    assert '"public/barca.ics"' not in workflow.split("paths:", 1)[1].split("permissions:", 1)[0]
    assert "concurrency:" in workflow
    assert "cancel-in-progress: true" in workflow
