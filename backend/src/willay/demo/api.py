"""The public demo's API: whether it is on for the user's organization, the Rímac
scenario's progress, and the button that starts it.

GET answers every role, also outside the demo (`available: false`), so the dashboard asks
without knowing how the server is set up. POST is for admins of the demo organization; the demo
worker picks the run up within seconds.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from willay.demo import live
from willay.demo.runs import DemoRun, RunKind, SqlDemoRuns, demo_organization
from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission, can
from willay.identity.domain.principal import Principal
from willay.shared.errors import ErrorCode
from willay.shared.web import ApiError, ClockDep, DbConnection, SettingsDep

router = APIRouter(prefix="/v1/demo", tags=["demo"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW))]
CanRun = Annotated[Principal, Depends(require(Permission.RUN_DEMO))]


class TimelineStepOut(BaseModel):
    phase: live.Phase
    at_s: int  # seconds after the run starts


class DemoRunOut(BaseModel):
    id: int
    kind: Literal["scenario", "restore"]
    status: Literal["queued", "running", "done", "failed"]
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # A scenario that is playing: where the story is.
    phase: live.Phase | None
    elapsed_s: int | None


class DemoOut(BaseModel):
    available: bool  # the demo is on and this is its organization
    can_run: bool
    duration_s: int
    timeline: list[TimelineStepOut]
    # The unfinished run, else the latest scenario.
    run: DemoRunOut | None


@router.get("", summary="Whether the public demo is on for the user's organization, and its run")
async def get_demo(
    principal: CanView, conn: DbConnection, settings: SettingsDep, clock: ClockDep
) -> DemoOut:
    organization_id = demo_organization(settings)
    available = organization_id == principal.organization_id
    run = None
    if available:
        runs = SqlDemoRuns(conn)
        current = await runs.active(principal.organization_id) or await runs.latest(
            principal.organization_id, RunKind.SCENARIO
        )
        run = _run_out(current, clock.now()) if current is not None else None
    return DemoOut(
        available=available,
        can_run=available and can(principal, Permission.RUN_DEMO),
        duration_s=live.DURATION_S,
        timeline=[TimelineStepOut(phase=phase, at_s=at_s) for phase, at_s in live.TIMELINE],
        run=run,
    )


@router.post(
    "/scenario",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the Rímac scenario: the demo worker plays it within seconds",
    responses={
        404: {"description": "The demo is off, or this is not its organization"},
        409: {"description": "A run is already in progress"},
    },
)
async def start_scenario(
    principal: CanRun, conn: DbConnection, settings: SettingsDep, clock: ClockDep
) -> DemoRunOut:
    if demo_organization(settings) != principal.organization_id:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.DEMO_UNAVAILABLE)
    now = clock.now()
    run = await SqlDemoRuns(conn).request(
        principal.organization_id, RunKind.SCENARIO, principal.user_id, now
    )
    if run is None:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.DEMO_RUN_ACTIVE)
    return _run_out(run, now)


def _run_out(run: DemoRun, now: datetime) -> DemoRunOut:
    playing = (
        run.kind is RunKind.SCENARIO and run.started_at is not None and run.finished_at is None
    )
    elapsed = int((now - run.started_at).total_seconds()) if playing and run.started_at else None
    return DemoRunOut(
        id=run.id,
        kind=run.kind.value,
        status=_status(run),
        requested_at=run.requested_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        phase=live.phase_at(elapsed) if elapsed is not None else None,
        elapsed_s=elapsed,
    )


def _status(run: DemoRun) -> Literal["queued", "running", "done", "failed"]:
    if run.outcome is not None:
        return run.outcome.value
    return "running" if run.started_at is not None else "queued"
