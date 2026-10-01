from pathlib import Path

from vigia.api.openapi import render

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def test_committed_openapi_matches_the_app() -> None:
    assert CONTRACT.exists(), "docs/openapi.json is missing: run `make openapi`"
    assert CONTRACT.read_text(encoding="utf-8") == render(), (
        "docs/openapi.json does not match the API: run `make openapi` and commit it in the PR"
    )
