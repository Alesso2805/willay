"""VIG-42: `make secrets` writes a server's .env (infra/scripts/production-env.sh)."""

import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "infra" / "scripts" / "production-env.sh"
CREDENTIALS = (
    "POSTGRES_PASSWORD",
    "WILLAY_OWNER_PASSWORD",
    "WILLAY_APP_PASSWORD",
    "KEYCLOAK_DB_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "WILLAY_DEV_USER_PASSWORD",
)
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="needs a POSIX sh (on Windows, Git Bash's)")


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert SH is not None
    return subprocess.run(
        [SH, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _env(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    pairs = (line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    return {key: value for key, value in pairs}


@pytest.fixture
def server(tmp_path: Path) -> Path:
    """A server's checkout, as far as the script is concerned: only .env.example."""
    shutil.copy(REPO / ".env.example", tmp_path / ".env.example")
    return tmp_path


def test_writes_new_credentials_the_hostname_and_the_production_overlay(server: Path) -> None:
    result = _run(server, "willay.example.org", "")
    assert result.returncode == 0, result.stderr

    env, example = _env(server / ".env"), _env(server / ".env.example")
    secrets = [env[key] for key in CREDENTIALS]
    # Hex only: these end up inside database URLs, where /, + or = would break them.
    assert all(re.fullmatch(r"[0-9a-f]{48}", secret) for secret in secrets)
    assert len(set(secrets)) == len(secrets)
    assert all(env[key] != example[key] for key in CREDENTIALS)
    assert env["COMPOSE_FILE"] == "docker-compose.yml:docker-compose.prod.yml"
    assert env["WILLAY_HOSTNAME"] == "willay.example.org"
    assert "COMPOSE_PROFILES" not in env
    assert "WILLAY_DEMO_MODE" not in env
    assert all(env[key] == value for key, value in example.items() if key not in CREDENTIALS)
    if sys.platform != "win32":  # Windows has no Unix permissions to check
        assert stat.S_IMODE((server / ".env").stat().st_mode) == 0o600


def test_with_demo_it_turns_the_public_demo_on(server: Path) -> None:
    result = _run(server, "willay.example.org", "1")
    assert result.returncode == 0, result.stderr

    env = _env(server / ".env")
    assert (env["COMPOSE_PROFILES"], env["WILLAY_DEMO_MODE"]) == ("demo", "true")
    assert env["WILLAY_DEMO_PASSWORD"] == "willay-demo"  # shown on the sign-in screen on purpose


def test_it_needs_a_hostname_and_never_overwrites_an_env(server: Path) -> None:
    assert _run(server).returncode == 2
    assert not (server / ".env").exists()

    (server / ".env").write_text("KEEP=1\n")
    assert _run(server, "willay.example.org", "").returncode == 1
    assert (server / ".env").read_text() == "KEEP=1\n"
