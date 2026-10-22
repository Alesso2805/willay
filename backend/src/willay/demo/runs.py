"""The public demo's runs: a queue in Postgres, like the evaluator's (ADR-0002).

The API inserts a scenario run when a visitor presses the button; the demo worker inserts a
restore run every night. The worker takes the organization's only unfinished run, plays it and
closes it with its outcome. A partial unique index keeps that run alone: inserting a second one
returns nothing, which the API answers with 409.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.seed import data as seed
from willay.shared.config import Settings


class RunKind(StrEnum):
    SCENARIO = "scenario"  # the Rímac story, from a clean slate
    RESTORE = "restore"  # the organization back as the seed made it


class Outcome(StrEnum):
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class DemoRun:
    id: int
    organization_id: UUID
    kind: RunKind
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    outcome: Outcome | None
    error: str | None


def demo_organization(settings: Settings) -> UUID | None:
    """The organization the public demo plays in, or None when the demo is off."""
    if not settings.demo_mode:
        return None
    return settings.demo_organization_id or seed.RIMAC.id


_COLUMNS = """
    id, organization_id, kind, requested_at, started_at, finished_at, outcome, error
"""
_REQUEST = text(f"""
    INSERT INTO core.demo_runs (organization_id, kind, requested_by, requested_at)
    VALUES (:organization_id, :kind, :requested_by, :now)
    ON CONFLICT (organization_id) WHERE finished_at IS NULL DO NOTHING
    RETURNING {_COLUMNS}
""")
_ACTIVE = text(f"""
    SELECT {_COLUMNS} FROM core.demo_runs
    WHERE organization_id = :organization_id AND finished_at IS NULL
""")
_LATEST = text(f"""
    SELECT {_COLUMNS} FROM core.demo_runs
    WHERE organization_id = :organization_id AND kind = :kind
    ORDER BY id DESC LIMIT 1
""")
_LAST_RESTORE = text("""
    SELECT max(finished_at) FROM core.demo_runs
    WHERE organization_id = :organization_id AND kind = 'restore'
""")
_START = text("UPDATE core.demo_runs SET started_at = :now WHERE id = :id")
_FINISH = text("""
    UPDATE core.demo_runs SET finished_at = :now, outcome = :outcome, error = :error
    WHERE id = :id AND finished_at IS NULL
""")


class SqlDemoRuns:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def request(
        self, organization_id: UUID, kind: RunKind, requested_by: UUID | None, now: datetime
    ) -> DemoRun | None:
        """The new queued run, or None if one is already unfinished."""
        params = {
            "organization_id": organization_id,
            "kind": kind,
            "requested_by": requested_by,
            "now": now,
        }
        row = (await self._conn.execute(_REQUEST, params)).first()
        return _run(row) if row is not None else None

    async def active(self, organization_id: UUID) -> DemoRun | None:
        row = (await self._conn.execute(_ACTIVE, {"organization_id": organization_id})).first()
        return _run(row) if row is not None else None

    async def latest(self, organization_id: UUID, kind: RunKind) -> DemoRun | None:
        params = {"organization_id": organization_id, "kind": kind}
        row = (await self._conn.execute(_LATEST, params)).first()
        return _run(row) if row is not None else None

    async def last_restore(self, organization_id: UUID) -> datetime | None:
        last: datetime | None = await self._conn.scalar(
            _LAST_RESTORE, {"organization_id": organization_id}
        )
        return last

    async def start(self, run_id: int, now: datetime) -> None:
        await self._conn.execute(_START, {"id": run_id, "now": now})

    async def finish(
        self, run_id: int, now: datetime, outcome: Outcome, error: str | None = None
    ) -> None:
        params = {"id": run_id, "now": now, "outcome": outcome, "error": error}
        await self._conn.execute(_FINISH, params)


def _run(r: Row[Any]) -> DemoRun:
    return DemoRun(
        id=r.id,
        organization_id=r.organization_id,
        kind=RunKind(r.kind),
        requested_at=r.requested_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        outcome=Outcome(r.outcome) if r.outcome is not None else None,
        error=r.error,
    )
