"""What `make demo` says while the Rímac scenario runs, and whether it went as SPEC says.

Pure: database rows arrive as plain values, so the narration and the verdict are tested without
a stack. SPEC's story: the downstream drop and the upstream silence open one incident each,
level 1 is alerted, nobody acknowledges, level 2 is alerted and acknowledges both. Level 3 must
never be reached.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from willay.incidents.domain.lifecycle import IncidentStatus
from willay.ingestion.domain.simulation import Behavior, StationPlan
from willay.seed import data as seed

DROP_RULE = next(
    r.id for r in seed.RULES if r.station_id == seed.S_CHACLACAYO and r.type == "rate_of_change"
)
SILENCE_RULE = next(
    r.id for r in seed.RULES if r.station_id == seed.S_SANTA_EULALIA and r.type == "silence"
)
CAUSES = {DROP_RULE: "drop", SILENCE_RULE: "silence"}

ACK_LEVEL = 2
# Generous: an incident opens within seconds of its reading (silence: K x interval + one 15 s
# cycle). Past this, something is off, usually the workers.
OPEN_GRACE_S = 90.0

_CHANNELS = {"email": "email", "telegram": "Telegram"}
_STATIONS = {s.code: s for s in seed.STATIONS}


@dataclass(frozen=True)
class IncidentState:
    id: UUID
    rule_id: UUID
    status: IncidentStatus
    current_level: int
    acknowledged: bool
    exhausted: bool


@dataclass(frozen=True)
class Case:
    """One of the story's two incidents: what the scenario did and what Willay made of it."""

    cause: str
    incident: IncidentState | None
    since_event_s: float | None  # since the scenario produced it; None: not yet


class Outcome(StrEnum):
    WAITING = "waiting"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    reason: str = ""


def judge(cases: Sequence[Case]) -> Verdict:
    for case in cases:
        problem = _problem(case)
        if problem is not None:
            return Verdict(Outcome.FAILED, problem)
    if all(case.incident is not None and case.incident.acknowledged for case in cases):
        return Verdict(Outcome.PASSED)
    return Verdict(Outcome.WAITING)


def _problem(case: Case) -> str | None:
    incident = case.incident
    if incident is None:
        if case.since_event_s is not None and case.since_event_s > OPEN_GRACE_S:
            return (
                f"the {case.cause} opened no incident within {OPEN_GRACE_S:.0f} s:"
                " are the workers running?"
            )
        return None
    if incident.acknowledged:
        if incident.current_level != ACK_LEVEL:
            return (
                f"the {case.cause} incident was acknowledged at level {incident.current_level};"
                f" the story needs level {ACK_LEVEL} to acknowledge it"
            )
        return None
    if incident.status is IncidentStatus.RESOLVED:
        return f"the {case.cause} incident was resolved without being acknowledged"
    if incident.current_level > ACK_LEVEL:
        return (
            f"nobody at level {ACK_LEVEL} acknowledged the {case.cause} incident:"
            f" it escalated to level {incident.current_level}"
        )
    if incident.exhausted:
        return f"the {case.cause} incident exhausted its escalation without an acknowledgement"
    return None


class AckMode(StrEnum):
    AUTO = "auto"  # Telegram if someone at level 2 has it linked, else email
    TELEGRAM = "telegram"  # a person presses the button in Telegram
    EMAIL = "email"  # the demo presses Confirm in a level-2 contact's email


def choose_mode(requested: AckMode, telegram: Sequence[str], email: Sequence[str]) -> AckMode | str:
    """How level 2 acknowledges, given who there has Telegram linked and who gets email. A
    string says why it cannot."""
    if requested is AckMode.AUTO:
        if telegram:
            return AckMode.TELEGRAM
        if email:
            return AckMode.EMAIL
        return f"Nobody at level {ACK_LEVEL} gets Telegram or email: nobody could acknowledge."
    if requested is AckMode.TELEGRAM and not telegram:
        return (
            f"Nobody at level {ACK_LEVEL} has Telegram linked: link one from Contactos"
            " (Generar enlace de Telegram), or run with --confirm email."
        )
    if requested is AckMode.EMAIL and not email:
        return f"Nobody at level {ACK_LEVEL} gets email: the demo cannot acknowledge for them."
    return requested


@dataclass(frozen=True)
class StoryEvent:
    """A timeline event with the names the narration needs (joined by the query)."""

    id: int
    incident_id: UUID
    rule_id: UUID
    occurred_at: datetime
    event_type: str
    actor_type: str
    payload: Mapping[str, Any]
    actor_name: str | None
    contact_name: str | None
    station_code: str | None
    # A contact's acknowledgement: the channel of the alert they acknowledged from.
    acknowledged_channel: str | None = None


def cause_of(event: StoryEvent) -> str:
    return CAUSES.get(event.rule_id, "other")


def narrate(event: StoryEvent) -> str:
    """The event in one line, in the same terms as the dashboard's timeline."""
    p = event.payload
    who = event.actor_name or "someone"
    recipient = event.contact_name or "a contact"
    channel = _CHANNELS.get(str(p.get("channel")), str(p.get("channel", "")))
    level = f"level {p.get('level_order')}"
    match event.event_type:
        case "opened":
            return f"incident opened at {event.station_code or 'the zone'}: {_opening(p)}"
        case "reading_added":
            return f"worse: new reading {_number(p.get('value'))}"
        case "alert_sent":
            return f"{level}: {channel} sent to {recipient}"
        case "alert_failed" if p.get("final"):
            return f"{level}: could not reach {recipient} by {channel}"
        case "alert_failed":
            return f"{level}: {channel} to {recipient} failed; it will be retried"
        case "alert_skipped":
            why = p.get("reason_code") or p.get("reason", "")
            return f"{level}: {recipient} skipped on {channel} ({str(why).replace('_', ' ')})"
        case "escalated":
            return f"nobody acknowledged: escalated to level {p.get('to_level')}"
        case "escalation_exhausted":
            return "escalation exhausted: nobody acknowledged at any level"
        case "station_recovered":
            return f"{event.station_code} reports again"
        case "acknowledged":
            used = _CHANNELS.get(event.acknowledged_channel or "")
            return f"acknowledged by {who}" + (f" from their {used} alert" if used else "")
        case "resolved" if p.get("resolution") == "false_alarm":
            return f"marked as a false alarm by {who}"
        case "resolved":
            return f"resolved by {who}"
        case "comment":
            return f"comment by {who}: {p.get('text', '')}"
        case _:
            return event.event_type


def _opening(p: Mapping[str, Any]) -> str:
    value = p.get("trigger_value")
    params = p.get("rule_params") or {}
    match p.get("rule_type"):
        case "rate_of_change":
            direction = "rise" if params.get("direction") == "up" else "drop"
            return f"sudden {direction}, value {_number(value)}"
        case "silence":
            return "the station stopped reporting" + (
                f", last value {_number(value)}" if value is not None else ""
            )
        case _:
            return f"value out of bounds, {_number(value)}"


def hint(event: StoryEvent, dashboard_url: str) -> str | None:
    """What the presenter can do or show after this event, if anything."""
    if event.event_type == "opened":
        return f"see it in the dashboard: {dashboard_url}/incidentes/{event.incident_id}"
    if event.event_type == "escalated" and event.payload.get("to_level") == ACK_LEVEL:
        return (
            f"level {ACK_LEVEL} can acknowledge now: the Telegram button, or the link in its"
            " email (Mailpit)"
        )
    return None


def scenario_notes(
    plans: Sequence[StationPlan],
    step: int,
    values: Mapping[str, float | None],
    previous: Mapping[str, float | None],
) -> list[str]:
    """What the simulated river does at this step, when it does something."""
    notes = []
    for plan in plans:
        if plan.behavior is Behavior.NORMAL or step != plan.event_step:
            continue
        station = _STATIONS.get(plan.code)
        name = f"{plan.code} ({station.name})" if station else plan.code
        if plan.behavior is Behavior.DROP:
            unit = f" {station.unit}" if station else ""
            notes.append(
                f"{name}: {plan.variable} falls from {_number(previous.get(plan.code))}"
                f" to {_number(values.get(plan.code))}{unit}"
            )
        elif plan.behavior is Behavior.SILENCE:
            notes.append(f"{name} stops reporting")
        else:
            notes.append(f"{name} starts to rise")
    return notes


def summary(events: Sequence[StoryEvent]) -> list[str]:
    """One line per incident of the story: who acknowledged it and how long it took."""
    lines = []
    for cause in CAUSES.values():
        own = [e for e in events if cause_of(e) == cause]
        opened = next((e for e in own if e.event_type == "opened"), None)
        acknowledged = next((e for e in own if e.event_type == "acknowledged"), None)
        if opened is None or acknowledged is None:
            continue
        took = (acknowledged.occurred_at - opened.occurred_at).total_seconds()
        lines.append(
            f"{cause}: opened at {opened.station_code}, acknowledged by"
            f" {acknowledged.actor_name or 'someone'} {clock_text(took)} later"
        )
    return lines


def status_line(elapsed_s: float, cases: Sequence[Case]) -> str:
    """A reminder of where the story stands, for the quiet minutes between events."""
    parts = [f"{case.cause}: {_state(case)}" for case in cases]
    return f"{clock_text(elapsed_s)} elapsed · " + " · ".join(parts)


def _state(case: Case) -> str:
    incident = case.incident
    if incident is None:
        return "not yet" if case.since_event_s is None else "opening"
    if incident.acknowledged:
        return f"acknowledged at level {incident.current_level}"
    return f"{incident.status} at level {incident.current_level}"


def clock_text(seconds: float) -> str:
    """75 -> '1:15'."""
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def _number(value: object) -> str:
    return f"{value:g}" if isinstance(value, int | float) else str(value)
