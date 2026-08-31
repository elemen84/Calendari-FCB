#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def parse_args(*, interval_hours: int) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Actualitza el calendari del FC Barcelona")
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"ignora el gate de {interval_hours} hores",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="consulta i valida sense escriure fitxers"
    )
    return parser.parse_args()


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from src.config import SYNC_INTERVAL_HOURS, load_config
    from src.http_client import OfficialHttpError, RequestsJsonClient
    from src.providers.common import SourceDataError
    from src.providers.copa import CopaProvider
    from src.providers.laliga import LaLigaProvider
    from src.providers.uefa import UEFAProvider
    from src.sync import build_calendar, load_sync_state, persist_build, should_sync

    args = parse_args(interval_hours=SYNC_INTERVAL_HOURS)
    try:
        config = load_config()
        now = datetime.now(ZoneInfo(config.timezone))
        state_path = ROOT / "data" / "sync-state.json"
        state = load_sync_state(state_path)
        if not should_sync(state, now, force=args.force):
            print(
                "Sync omès: encara no han passat "
                f"{SYNC_INTERVAL_HOURS} hores des de l'últim sync correcte."
            )
            return 0

        client = RequestsJsonClient()
        laliga = LaLigaProvider(config, client)
        uefa = UEFAProvider(config, client)
        copa = CopaProvider(config, client)
        fetched = {
            "laliga": (laliga, laliga.fetch()),
            "champions": (uefa, uefa.fetch()),
            "copa-del-rey": (copa, copa.fetch()),
        }
        build = build_calendar(
            config,
            fetched,
            cache_root=ROOT / "data" / "provider-cache",
            standings_root=ROOT / "data" / "standings",
            now=now,
        )
        counts = {key: len(result.games) for key, result in build.provider_results.items()}
        print(
            "Partits detectats: "
            f"LaLiga={counts.get('laliga', 0)}, "
            f"Champions={counts.get('champions', 0)}, "
            f"Copa={counts.get('copa-del-rey', 0)}"
        )
        if args.dry_run:
            print("Dry-run: cap fitxer modificat.")
            return 0
        persist_build(
            build,
            config=config,
            cache_root=ROOT / "data" / "provider-cache",
            standings_root=ROOT / "data" / "standings",
            ics_path=ROOT / "public" / "barca.ics",
            state_path=state_path,
            now=now,
        )
        print("Sync correcte: public/barca.ics i dades persistents actualitzades.")
        return 0
    except (OfficialHttpError, SourceDataError, RuntimeError, ValueError) as exc:
        print(f"Sync aturat en fail-closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
