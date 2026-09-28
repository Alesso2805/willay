"""Contrato OpenAPI versionado: `python -m vigia.api.openapi [ruta]` (o `make openapi`).

docs/openapi.json se revisa en el mismo PR que el cambio de endpoint; un test falla
si el archivo no coincide con lo que genera la app.
"""

import json
import sys
from pathlib import Path
from typing import Any

from vigia.api.main import create_app
from vigia.shared.config import Settings

# Generar el esquema no necesita base de datos: el lifespan no se ejecuta.
_SETTINGS = Settings(database_url="postgresql+asyncpg://unused/unused")


def render() -> str:
    schema: dict[str, Any] = create_app(_SETTINGS).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../docs/openapi.json")
    target.write_text(render(), encoding="utf-8", newline="\n")
    print(f"OpenAPI escrito en {target}")


if __name__ == "__main__":
    main()
