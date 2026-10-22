"""`make demo`: SPEC's Rímac scenario, narrated, with a verdict.

It runs in the migrate container (`docker compose run`), like `make loadtest`: it reaches the
database and the API (`http://api:8000`) over the compose network, and reads the stations' API
keys from the file `make seed` wrote (.secrets/station-keys.json, mounted read-only).

1. Checks the stack: the API answers, the keys exist, both demo rules are active and their
   policy has a level 2.
2. Clears the demo organization's operational data (willay.demo.reset).
3. Runs the `rimac` scenario and narrates every timeline event until level 2 acknowledges both
   incidents (PASS, exit 0) or the story goes wrong (FAIL, exit 1).
4. After a PASS the stations keep reporting, so the dashboard stays live, until Ctrl+C. On the
   way out they are parked, so no silence incident opens after the demo.
"""

import argparse
import asyncio
import contextlib
import math
import os
import signal
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy.ext.asyncio import AsyncEngine

from willay.demo import progress, reset
from willay.demo.mailbox import EmailAcknowledger, MailpitMailbox
from willay.demo.progress import Readiness
from willay.demo.story import (
    ACK_LEVEL,
    CAUSES,
    AckMode,
    Case,
    Outcome,
    StoryEvent,
    Verdict,
    cause_of,
    choose_mode,
    clock_text,
    hint,
    judge,
    narrate,
    scenario_notes,
    status_line,
    summary,
)
from willay.ingestion.api.simulator_cli import load_stations
from willay.ingestion.application.simulate import SimulatedStation, TickReport, run_simulation
from willay.ingestion.domain.simulation import (
    RIMAC_DOWNSTREAM,
    RIMAC_SILENCE_DELAY_S,
    RIMAC_UPSTREAM,
    Behavior,
    Scenario,
    StationPlan,
    build_plan,
)
from willay.ingestion.infrastructure.http_sender import HttpReadingSender
from willay.seed import data as seed
from willay.shared.clock import SystemClock
from willay.shared.config import get_settings
from willay.shared.db import create_engine

INTERVAL_S = 10.0  # the seed stations' expected interval
POLL_S = 2.0
STATUS_EVERY_S = 60.0
TIMEOUT_S = 15 * 60  # the whole story takes about 8 minutes
EVENT_CAUSES = {Behavior.DROP: "drop", Behavior.SILENCE: "silence"}
_TZ = ZoneInfo(seed.RIMAC.timezone)
_VARIABLES = {station.code: station.variable for station in seed.STATIONS}


@dataclass
class _Run:
    passed: bool = False
    happened: dict[str, datetime] = field(default_factory=dict)  # cause -> when the river did it
    previous: dict[str, float | None] = field(default_factory=dict)  # last step's values


def _say(text: str = "") -> None:
    print(text, flush=True)  # without a terminal (a log file) output is buffered until the end


def _line(at: datetime, tag: str, text: str) -> str:
    return f"{at.astimezone(_TZ):%H:%M:%S}  {f'[{tag}]':<9}  {text}"


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m willay.demo", description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="same seed, same readings (42)")
    parser.add_argument("--event-after", type=float, default=60, help="seconds until the drop (60)")
    parser.add_argument("--keys-file", type=Path, default=Path("/secrets/station-keys.json"))
    parser.add_argument("--api-url", default="http://api:8000", help="where readings are sent")
    parser.add_argument("--dashboard-url", default="http://localhost:4200", help="for links")
    parser.add_argument("--mailpit-url", default="http://localhost:8025", help="for links")
    parser.add_argument(
        "--confirm",
        type=AckMode,
        choices=list(AckMode),
        default=AckMode.AUTO,
        help="how level 2 acknowledges: telegram (you press the button), email (the demo"
        " presses Confirm in a level-2 contact's email) or auto (telegram if linked)",
    )
    parser.add_argument("--mailpit-api", default="http://mailpit:8025", help="to read emails")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace, run: _Run) -> int:
    keys = dict(load_stations(args.keys_file, seed.RIMAC.alias, None))
    missing = {RIMAC_DOWNSTREAM, RIMAC_UPSTREAM} - keys.keys()
    if missing:
        _say(f"No API keys for {sorted(missing)} in {args.keys_file}: run make seed.")
        return 1
    if not await _api_answers(args.api_url):
        _say(f"The API does not answer at {args.api_url}: start the stack (make up).")
        return 1
    owner_url = os.environ.get("WILLAY_MIGRATE_DATABASE_URL")
    if not owner_url:
        _say("WILLAY_MIGRATE_DATABASE_URL is missing: make demo runs in the migrate container.")
        return 1

    _stop_on_sigterm()
    app_engine = create_engine(get_settings().database_url)
    owner_engine = create_engine(owner_url)
    clients = contextlib.AsyncExitStack()
    simulation: asyncio.Task[None] | None = None
    try:
        async with app_engine.connect() as conn:
            ready = await progress.readiness(conn, list(CAUSES), ACK_LEVEL)
        problem = _not_ready(ready)
        by_email = [recipient.name for recipient in ready.email_at_ack_level]
        mode = choose_mode(args.confirm, ready.telegram_at_ack_level, by_email)
        # Not isinstance(mode, str): AckMode is a StrEnum, so every chosen mode is a str too.
        if problem is not None or not isinstance(mode, AckMode):
            _say(problem or str(mode))
            return 1
        acknowledger = None
        if mode is AckMode.EMAIL:
            acknowledger = await _acknowledger(args, ready, app_engine, clients)
        plans = build_plan(
            Scenario.RIMAC,
            [(code, _VARIABLES.get(code, "discharge")) for code in sorted(keys)],
            event_step=math.ceil(args.event_after / INTERVAL_S),
            interval_s=INTERVAL_S,
        )
        _introduce(args, len(plans), ready, acknowledger)
        async with owner_engine.begin() as conn:
            cleared = await reset.clear(conn, seed.RIMAC.id)
        _say(
            f"Cleared the previous runs: {_count(cleared.incidents, 'incident')},"
            f" {_count(cleared.readings, 'reading')}. Reload the dashboard if it was open.\n"
        )
        since = SystemClock().now()
        simulation = asyncio.create_task(_simulate(args, plans, keys, run))
        verdict, story = await _watch(
            app_engine, run, since, args.dashboard_url, simulation, acknowledger
        )
        if verdict.outcome is Outcome.FAILED:
            _say(f"\nFAIL: {verdict.reason}")
            return 1
        run.passed = True
        _say(f"\nPASS: level {ACK_LEVEL} acknowledged both incidents.")
        for line in summary(story):
            _say(f"  {line}")
        _say(
            f"\nThe whole timeline is in the dashboard ({args.dashboard_url}/incidentes)."
            " The stations keep reporting so it stays live: Ctrl+C to finish."
        )
        await simulation  # until Ctrl+C
        return 0
    finally:
        if simulation is not None:
            simulation.cancel()
            await asyncio.gather(simulation, return_exceptions=True)
            async with owner_engine.begin() as conn:
                await reset.park(conn, seed.RIMAC.id)
            _say("Stations parked: no silence incident opens now that they stopped reporting.")
        await clients.aclose()
        await app_engine.dispose()
        await owner_engine.dispose()


def _stop_on_sigterm() -> None:
    """`docker stop` (or a closed terminal) ends the demo like Ctrl+C does: cancelling the
    main task runs _run's finally, which parks the stations. Without a handler, Python dies on
    SIGTERM without running it."""
    main = asyncio.current_task()
    if main is None:
        return
    with contextlib.suppress(NotImplementedError):  # Windows event loops have no signals
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, main.cancel)


async def _api_answers(api_url: str) -> bool:
    async with httpx2.AsyncClient(timeout=5) as client:
        try:
            (await client.get(f"{api_url}/health")).raise_for_status()
        except httpx2.HTTPError:
            return False
    return True


async def _acknowledger(
    args: argparse.Namespace,
    ready: Readiness,
    engine: AsyncEngine,
    clients: contextlib.AsyncExitStack,
) -> EmailAcknowledger:
    """Level 2's first contact with email, acknowledging through the confirmation page."""
    mail = await clients.enter_async_context(
        httpx2.AsyncClient(base_url=args.mailpit_api, timeout=10)
    )
    api = await clients.enter_async_context(httpx2.AsyncClient(base_url=args.api_url, timeout=10))

    async def lookup(token: str) -> tuple[UUID, int] | None:
        async with engine.connect() as conn:
            return await progress.alert_of_token(conn, token)

    async def confirm(token: str) -> int:
        # The link in the email points at the public URL (localhost); inside the compose
        # network the API is api:8000, so only the token is taken from it.
        return (await api.post(f"/confirmar/{token}")).status_code

    recipient = ready.email_at_ack_level[0]
    return EmailAcknowledger(recipient, MailpitMailbox(mail), lookup, confirm, SystemClock())


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _not_ready(ready: Readiness) -> str | None:
    if len(ready.rules) != len(CAUSES):
        return "The demo rules are missing: run make seed."
    for rule in ready.rules:
        if not rule.active:
            return f"The demo rule of {rule.station_code} is deactivated: reactivate it in Reglas."
    if ACK_LEVEL not in {level for level, _ in ready.levels}:
        return f"The demo rules' policy has no level {ACK_LEVEL}: the story needs one."
    return None


def _introduce(
    args: argparse.Namespace,
    stations: int,
    ready: Readiness,
    acknowledger: EmailAcknowledger | None,
) -> None:
    first_wait = dict(ready.levels).get(1, 0)
    ack_wait = dict(ready.levels).get(ACK_LEVEL, 0)
    drop = args.event_after
    timeline = [
        (0, f"{stations} stations report every {INTERVAL_S:g} s"),
        (drop, f"{RIMAC_DOWNSTREAM} (downstream): sudden discharge drop -> incident, level 1"),
        (drop + first_wait, f"nobody acknowledges in {clock_text(first_wait)} -> level 2"),
        (drop + RIMAC_SILENCE_DELAY_S, f"{RIMAC_UPSTREAM} (upstream) stops -> second incident"),
    ]
    _say("Willay demo: something dams the Rímac between Santa Eulalia and Chaclacayo.")
    for at, text in timeline:
        _say(f"  {clock_text(at):>5}  {text}")
    _say(
        f"  Level {ACK_LEVEL} acknowledges both, each within {clock_text(ack_wait)} of its"
        " alert: level 3 must not be reached."
    )
    if acknowledger is None:
        names = ", ".join(ready.telegram_at_ack_level)
        _say(f"  Level {ACK_LEVEL} on Telegram: {names}. Press «Confirmar que lo vi» on each.")
    else:
        why = "" if ready.telegram_at_ack_level else "Nobody there has Telegram linked: "
        _say(
            f"  {why}the demo acknowledges as {acknowledger.recipient.name}, pressing Confirm"
            f" in each level-{ACK_LEVEL} email ({args.mailpit_url})."
        )
    _say(f"Watch it live: {args.dashboard_url}/mapa · email: {args.mailpit_url}")
    # An acknowledgement from the dashboard at level 1 ends the story early: viewers cannot.
    _say("  Log in as rimac-viewer: a viewer cannot acknowledge, so the dashboard cannot end")
    _say(f"  the story before level {ACK_LEVEL} does.")
    _say()


async def _simulate(
    args: argparse.Namespace, plans: list[StationPlan], keys: dict[str, str], run: _Run
) -> None:
    stations = [SimulatedStation(plan, keys[plan.code]) for plan in plans]
    async with httpx2.AsyncClient(base_url=args.api_url, timeout=10.0) as client:
        await run_simulation(
            stations,
            seed=args.seed,
            interval_s=INTERVAL_S,
            steps=None,  # the stations keep reporting until the demo ends
            clock=SystemClock(),
            sleep=asyncio.sleep,
            sender=HttpReadingSender(client),
            on_tick=_on_tick(plans, run),
        )


def _on_tick(plans: Sequence[StationPlan], run: _Run) -> Callable[[TickReport], None]:
    def on_tick(report: TickReport) -> None:
        for note in scenario_notes(plans, report.step, report.values, run.previous):
            _say(_line(report.at, "river", note))
        for plan in plans:
            cause = EVENT_CAUSES.get(plan.behavior)
            if cause is not None and report.step == plan.event_step:
                run.happened[cause] = report.at
        rejected = {code: status for code, status in report.statuses.items() if status != 202}
        if rejected:
            _say(_line(report.at, "river", f"batches not accepted: {rejected}"))
        run.previous = dict(report.values)

    return on_tick


async def _watch(
    engine: AsyncEngine,
    run: _Run,
    since: datetime,
    dashboard_url: str,
    simulation: asyncio.Task[None],
    acknowledger: EmailAcknowledger | None,
) -> tuple[Verdict, list[StoryEvent]]:
    """Narrates new timeline events every couple of seconds until the verdict is in."""
    clock = SystemClock()
    story: list[StoryEvent] = []
    seen: set[int] = set()
    next_status = STATUS_EVERY_S
    while True:
        async with engine.connect() as conn:
            events = await progress.events(conn, seed.RIMAC.id, since)
            states = await progress.incidents(conn, seed.RIMAC.id, list(CAUSES), since)
        for event in events:
            if event.id in seen:
                continue
            seen.add(event.id)
            story.append(event)
            _say(_line(event.occurred_at, cause_of(event), narrate(event)))
            tip = hint(event, dashboard_url)
            if tip is not None:
                _say(f"{'':21}-> {tip}")
        now = clock.now()
        if acknowledger is not None:
            causes = {s.id: CAUSES[s.rule_id] for s in states.values()}
            try:
                for incident_id, note in await acknowledger.step(causes.keys()):
                    _say(_line(now, causes[incident_id], note))
            except httpx2.HTTPError as exc:
                reason = f"could not read the emails in Mailpit ({exc!r}): is it running?"
                return Verdict(Outcome.FAILED, reason), story
        cases = [
            Case(cause, states.get(rule_id), _since(run.happened.get(cause), now))
            for rule_id, cause in CAUSES.items()
        ]
        verdict = judge(cases)
        if verdict.outcome is not Outcome.WAITING:
            return verdict, story
        if simulation.done():
            error = simulation.exception() if not simulation.cancelled() else None
            return Verdict(Outcome.FAILED, f"the simulator stopped: {error!r}"), story
        elapsed = (now - since).total_seconds()
        if elapsed > TIMEOUT_S:
            reason = f"the story did not finish within {TIMEOUT_S // 60} min"
            return Verdict(Outcome.FAILED, reason), story
        if elapsed >= next_status:
            _say(f"{'':21}{status_line(elapsed, cases)}")
            next_status += STATUS_EVERY_S
        await asyncio.sleep(POLL_S)


def _since(at: datetime | None, now: datetime) -> float | None:
    return None if at is None else (now - at).total_seconds()


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    if not args.keys_file.exists():
        _say(f"{args.keys_file} does not exist: run make seed first.")
        return 1
    run = _Run()
    try:
        return asyncio.run(_run(args, run))
    except (KeyboardInterrupt, asyncio.CancelledError):  # Ctrl+C or SIGTERM, already parked
        _say("Demo finished.")
        return 0 if run.passed else 1


if __name__ == "__main__":
    sys.exit(main())
