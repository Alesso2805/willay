"""`python -m vigia.seed [--rotate-keys] [--keys-file RUTA]`

Carga los datos demo en una transacción e imprime las API keys emitidas. Con
--keys-file las fusiona en un JSON (por código de estación) que usa el simulador;
las claves ya guardadas se conservan si no se rotaron.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher
from vigia.seed.loader import IssuedKey, load_seed
from vigia.shared.clock import SystemClock
from vigia.shared.config import get_settings
from vigia.shared.db import create_engine


async def _run(rotate_keys: bool) -> list[IssuedKey]:
    engine = create_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:  # todo o nada
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
    parser = argparse.ArgumentParser(prog="python -m vigia.seed", description=__doc__)
    parser.add_argument(
        "--rotate-keys", action="store_true", help="emite claves nuevas para todas las estaciones"
    )
    parser.add_argument("--keys-file", type=Path, help="JSON donde fusionar las claves emitidas")
    args = parser.parse_args()
    # Validar antes de tocar la base: si el archivo no se puede escribir después del commit,
    # las claves emitidas solo quedarían en la terminal.
    if args.keys_file and not args.keys_file.parent.is_dir():
        parser.error(f"no existe el directorio de --keys-file: {args.keys_file.parent}")

    issued = asyncio.run(_run(args.rotate_keys))

    if not issued:
        print("Seed aplicado. Sin claves nuevas (las estaciones ya existían).")
        print("Usa --rotate-keys para emitir claves nuevas.")
    else:
        print(f"Seed aplicado. {len(issued)} API keys emitidas (se muestran solo esta vez):\n")
        for key in issued:
            print(f"  {key.organization_alias:<12} {key.station_code:<11} {key.api_key}")
    if args.keys_file and issued:
        _merge_keys_file(args.keys_file, issued)
        print(f"\nClaves guardadas en {args.keys_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
