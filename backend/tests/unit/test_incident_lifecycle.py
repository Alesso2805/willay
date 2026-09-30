from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tests.support.lifecycle import FakeIncidentRepository as Repository
from vigia.incidents.application.lifecycle import (
    Actor,
    ContactActor,
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
