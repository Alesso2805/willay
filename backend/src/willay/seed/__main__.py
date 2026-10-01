"""`python -m willay.seed [--rotate-keys] [--keys-file PATH]`

Loads the demo data in one transaction and prints the issued API keys. With --keys-file they
are merged into a JSON file (keyed by station code) used by the simulator; keys already stored
there are kept unless rotated.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from willay.ingestion.infrastructure.api_keys import ApiKeyHasher
from willay.seed.loader import IssuedKey, load_seed
from willay.shared.clock import SystemClock
from willay.shared.config import get_settings
from willay.shared.db import create_engine


async def _run(rotate_keys: bool) -> list[IssuedKey]:
    engine = create_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:  # all or nothing
            return await load_seed(conn, SystemClock(), ApiKeyHasher(), rotate_keys=rotate_keys)
    finally:
        await engine.dispose()


def _merge_keys_file(path: Path, issued: list[IssuedKey]) -> None:
    keys: dict[str, dict[str, str]] = json.loads(path.read_text()) if path.exists() else {}
    for key in issued:
        keys[key.station_code] = {
            "organization": key.organization_alias,
            "station_id": str(key.station_id),
            "api_key": key.api_key,
        }
    path.write_text(json.dumps(keys, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m willay.seed", description=__doc__)
    parser.add_argument(
        "--rotate-keys", action="store_true", help="issue new keys for every station"
    )
    parser.add_argument("--keys-file", type=Path, help="JSON file to merge the issued keys into")
    args = parser.parse_args()
    # Validate before touching the database: if the file cannot be written after the commit,
    # the issued keys would only exist in the terminal.
    if args.keys_file and not args.keys_file.parent.is_dir():
        parser.error(f"--keys-file directory does not exist: {args.keys_file.parent}")

    issued = asyncio.run(_run(args.rotate_keys))

    if not issued:
        print("Seed applied. No new keys (the stations already existed).")
        print("Use --rotate-keys to issue new keys.")
    else:
        print(f"Seed applied. {len(issued)} API keys issued (shown only this once):\n")
        for key in issued:
            print(f"  {key.organization_alias:<12} {key.station_code:<11} {key.api_key}")
    if args.keys_file and issued:
        _merge_keys_file(args.keys_file, issued)
        print(f"\nKeys saved to {args.keys_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
