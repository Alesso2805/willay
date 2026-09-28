from pathlib import Path

from vigia.api.openapi import render

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def test_committed_openapi_matches_the_app() -> None:
    assert CONTRACT.exists(), "Falta docs/openapi.json: ejecuta `make openapi`"
    assert CONTRACT.read_text(encoding="utf-8") == render(), (
        "docs/openapi.json no coincide con la API: ejecuta `make openapi` y súbelo en el PR"
    )
