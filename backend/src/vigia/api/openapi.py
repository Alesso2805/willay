"""Versioned OpenAPI contract: `python -m vigia.api.openapi [path]` (or `make openapi`).

docs/openapi.json is reviewed in the same PR as the endpoint change; a test fails if the file
does not match what the app generates.
"""

import json
import sys
from pathlib import Path
from typing import Any

from vigia.api.main import create_app
from vigia.shared.config import Settings

# Generating the schema needs no database: the lifespan does not run.
_SETTINGS = Settings(database_url="postgresql+asyncpg://unused/unused")


def render() -> str:
    schema: dict[str, Any] = create_app(_SETTINGS).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../docs/openapi.json")
    target.write_text(render(), encoding="utf-8", newline="\n")
    print(f"OpenAPI written to {target}")


if __name__ == "__main__":
    main()
