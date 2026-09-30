from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from vigia.incidents.application.lifecycle import (
    Actor,
    ContactActor,
    EventActor,
    Incident,
    IncidentEvent,
    IncidentNotFoundError,
    acknowledge_as_contact,
    acknowledge_incident,
    resolve_incident,
)
from vigia.incidents.domain.lifecycle import (
    IncidentStatus,
    InvalidTransitionError,
    Resolution,
    Transition,
    ensure_allowed,
)
from vigia.shared.clock import FakeClock

T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
OPEN, ACK, RESOLVED = IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED, IncidentStatus.RESOLVED


@pytest.mark.parametrize(
    ("transition", "current", "allowed"),
    [
        (Transition.ACKNOWLEDGE, OPEN, True),
        (Transition.ACKNOWLEDGE, ACK, False),
        (Transition.ACKNOWLEDGE, RESOLVED, False),
        (Transition.RESOLVE, OPEN, True),  # decisión de producto: sin confirmar antes
        (Transition.RESOLVE, ACK, True),
        (Transition.RESOLVE, RESOLVED, False),  # resuelto es final
    ],
)
def test_transitions(transition: Transition, current: IncidentStatus, allowed: bool) -> None:
    if allowed:
        ensure_allowed(transition, current)
    else:
        with pytest.raises(InvalidTransitionError) as caught:
            ensure_allowed(transition, current)
        assert caught.value.current is current


class Repository:
    """Un incidente en memoria, con los eventos que se le escriben."""

    def __init__(self, organization_id: UUID, status: IncidentStatus = OPEN) -> None:
        self.incident = Incident(
            id=uuid4(),
            zone_id=uuid4(),
            zone_name="Chosica",
            station_id=uuid4(),
            station_code="RIM-CHA-01",
            rule_id=uuid4(),
            rule_type="rate_of_change",
            severity="critical",
            status=status,
            current_level=1,
            trigger_value=34.2,
            opened_at=T0,
            escalation_exhausted_at=None,
            acknowledged_at=None,
            acknowledged_by_user_id=None,
            acknowledged_by_contact_id=None,
            resolved_at=None,
            resolution=None,
        )
        self.organization_id = organization_id
        self.events: list[tuple[str, UUID, Mapping[str, Any]]] = []

    def _mine(self, organization_id: UUID, incident_id: UUID) -> bool:
        return organization_id == self.organization_id and incident_id == self.incident.id

    async def recent(
        self, organization_id: UUID, statuses: Sequence[IncidentStatus], limit: int
    ) -> list[Incident]:
        return [self.incident]

    async def get(self, organization_id: UUID, incident_id: UUID) -> Incident | None:
        return self.incident if self._mine(organization_id, incident_id) else None

    async def timeline(self, incident_id: UUID) -> list[IncidentEvent]:
        return []

    async def lock_status(self, organization_id: UUID, incident_id: UUID) -> IncidentStatus | None:
        return self.incident.status if self._mine(organization_id, incident_id) else None

    async def acknowledge(self, incident_id: UUID, actor: EventActor, now: datetime) -> None:
        by_user = isinstance(actor, Actor)
        self.incident = replace(
            self.incident,
            status=ACK,
            acknowledged_at=now,
            acknowledged_by_user_id=actor.actor_id if by_user else None,
            acknowledged_by_contact_id=None if by_user else actor.actor_id,
        )

    async def resolve(self, incident_id: UUID, resolution: Resolution, now: datetime) -> None:
        self.incident = replace(
            self.incident, status=RESOLVED, resolved_at=now, resolution=resolution
        )

    async def add_event(
        self,
        incident_id: UUID,
        actor: EventActor,
        event_type: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> None:
        self.events.append((event_type, actor.actor_id, payload))


ACTOR = Actor(uuid4(), uuid4())


async def test_acknowledging_records_who_and_writes_the_event() -> None:
    repository = Repository(ACTOR.organization_id)
    incident = await acknowledge_incident(
        ACTOR, repository.incident.id, incidents=repository, clock=FakeClock(T0)
    )
    assert (incident.status, incident.acknowledged_at) == (ACK, T0)
    assert incident.acknowledged_by_user_id == ACTOR.user_id
    assert repository.events == [("acknowledged", ACTOR.user_id, {})]


async def test_resolving_an_open_incident_keeps_the_previous_status_in_the_event() -> None:
    repository = Repository(ACTOR.organization_id)
    incident = await resolve_incident(
        ACTOR,
        repository.incident.id,
        Resolution.FALSE_ALARM,
        incidents=repository,
        clock=FakeClock(T0),
    )
    assert (incident.status, incident.resolution) == (RESOLVED, Resolution.FALSE_ALARM)
    assert repository.events == [
        ("resolved", ACTOR.user_id, {"resolution": "false_alarm", "previous_status": "open"})
    ]


async def test_an_invalid_transition_changes_nothing() -> None:
    repository = Repository(ACTOR.organization_id, status=RESOLVED)
    with pytest.raises(InvalidTransitionError):
        await acknowledge_incident(
            ACTOR, repository.incident.id, incidents=repository, clock=FakeClock(T0)
        )
    assert (repository.incident.status, repository.events) == (RESOLVED, [])


async def test_another_organizations_incident_is_not_found() -> None:
    repository = Repository(organization_id=uuid4())
    with pytest.raises(IncidentNotFoundError):
        await resolve_incident(
            ACTOR,
            repository.incident.id,
            Resolution.RESOLVED,
            incidents=repository,
            clock=FakeClock(T0),
        )


@pytest.mark.parametrize("before", [OPEN, ACK, RESOLVED])
async def test_a_contact_acknowledges_only_an_open_incident_and_never_fails(
    before: IncidentStatus,
) -> None:
    repository = Repository(ACTOR.organization_id, status=before)
    contact = ContactActor(ACTOR.organization_id, uuid4())

    previous = await acknowledge_as_contact(
        contact, repository.incident.id, incidents=repository, clock=FakeClock(T0)
    )

    assert previous is before
    if before is OPEN:
        assert repository.incident.status is ACK
        assert repository.incident.acknowledged_by_contact_id == contact.contact_id
        assert repository.incident.acknowledged_by_user_id is None
        assert repository.events == [("acknowledged", contact.contact_id, {})]
    else:
        assert (repository.incident.status, repository.events) == (before, [])
