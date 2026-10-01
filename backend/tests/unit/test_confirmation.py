from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tests.support.lifecycle import ACK, OPEN, RESOLVED, T0, FakeIncidentRepository
from tests.unit.test_email_alerts import MESSAGE
from willay.alerts.application.confirmation import (
    AlertToConfirm,
    confirm_alert,
    preview_confirmation,
)
from willay.alerts.domain.confirmation import ConfirmOutcome, token_problem
from willay.alerts.domain.delivery import hash_ack_token
from willay.incidents.domain.lifecycle import IncidentStatus
from willay.shared.clock import FakeClock

TOKEN = "t" * 43
EXPIRES = T0 + timedelta(hours=24)


@pytest.mark.parametrize(
    ("expires_at", "used_at", "now", "problem"),
    [
        (EXPIRES, None, EXPIRES - timedelta(microseconds=1), None),
        (EXPIRES, None, EXPIRES, ConfirmOutcome.EXPIRED),  # no longer valid at exactly 24 h
        (None, None, T0, ConfirmOutcome.EXPIRED),  # no current token
        (EXPIRES, T0, T0, ConfirmOutcome.USED),  # single use
    ],
)
def test_a_token_is_single_use_and_lasts_24_hours(
    expires_at: datetime | None,
    used_at: datetime | None,
    now: datetime,
    problem: ConfirmOutcome | None,
) -> None:
    assert token_problem(expires_at, used_at, now) is problem


class Confirmations:
    """One alert with its token; the incident status comes from the fake repository."""

    def __init__(self, incidents: FakeIncidentRepository) -> None:
        self.incidents = incidents
        self.alert = AlertToConfirm(
            alert_id=uuid4(),
            incident_id=incidents.incident.id,
            organization_id=incidents.organization_id,
            contact_id=uuid4(),
            destination="4242",
            token_expires_at=EXPIRES,
            used_at=None,
            incident_status=incidents.incident.status,
            incident_acknowledged_at=None,
            acknowledged_by=None,
            message=MESSAGE,
        )
        self.locks: list[bool] = []

    async def find(self, token_hash: str, *, lock: bool) -> AlertToConfirm | None:
        self.locks.append(lock)
        if token_hash != hash_ack_token(TOKEN):
            return None
        incident = self.incidents.incident
        return replace(
            self.alert,
            incident_status=incident.status,
            incident_acknowledged_at=incident.acknowledged_at,
        )

    async def mark_acknowledged(self, alert_id: UUID, now: datetime) -> None:
        self.alert = replace(self.alert, used_at=now)


def _setup(status: IncidentStatus = OPEN) -> tuple[FakeIncidentRepository, Confirmations]:
    incidents = FakeIncidentRepository(uuid4(), status=status)
    return incidents, Confirmations(incidents)


async def test_opening_the_link_changes_nothing() -> None:
    incidents, confirmations = _setup()
    view = await preview_confirmation(TOKEN, confirmations=confirmations, clock=FakeClock(T0))

    assert (view.outcome, view.alert is not None) == (None, True)
    assert confirmations.locks == [False]
    assert (incidents.incident.status, incidents.events, confirmations.alert.used_at) == (
        OPEN,
        [],
        None,
    )


async def test_confirming_acknowledges_the_incident_as_the_contact() -> None:
    incidents, confirmations = _setup()
    view = await confirm_alert(
        TOKEN, confirmations=confirmations, incidents=incidents, clock=FakeClock(T0)
    )

    assert view.outcome is ConfirmOutcome.CONFIRMED
    assert confirmations.locks[0] is True  # locked so two clicks do not confirm twice
    contact = confirmations.alert.contact_id
    assert incidents.incident.acknowledged_by_contact_id == contact
    assert incidents.events == [("acknowledged", contact, {})]
    assert confirmations.alert.used_at == T0

    again = await confirm_alert(
        TOKEN, confirmations=confirmations, incidents=incidents, clock=FakeClock(T0)
    )
    assert again.outcome is ConfirmOutcome.USED


async def test_someone_else_was_first_the_alert_is_recorded_as_seen() -> None:
    incidents, confirmations = _setup(ACK)
    view = await confirm_alert(
        TOKEN, confirmations=confirmations, incidents=incidents, clock=FakeClock(T0)
    )

    assert view.outcome is ConfirmOutcome.ALREADY_ACKNOWLEDGED
    assert incidents.events == []  # who acknowledged the incident does not change
    assert confirmations.alert.used_at == T0


async def test_a_resolved_incident_changes_nothing() -> None:
    incidents, confirmations = _setup(RESOLVED)
    clock = FakeClock(T0)

    preview = await preview_confirmation(TOKEN, confirmations=confirmations, clock=clock)
    view = await confirm_alert(TOKEN, confirmations=confirmations, incidents=incidents, clock=clock)

    assert preview.outcome is view.outcome is ConfirmOutcome.ALREADY_RESOLVED
    assert (incidents.events, confirmations.alert.used_at) == ([], None)


async def test_an_expired_or_unknown_token_changes_nothing() -> None:
    incidents, confirmations = _setup()
    late = FakeClock(EXPIRES)
    expired = await confirm_alert(
        TOKEN, confirmations=confirmations, incidents=incidents, clock=late
    )
    unknown = await confirm_alert(
        "x" * 43, confirmations=confirmations, incidents=incidents, clock=FakeClock(T0)
    )

    assert (expired.outcome, unknown.outcome) == (ConfirmOutcome.EXPIRED, ConfirmOutcome.UNKNOWN)
    assert unknown.alert is None
    assert (incidents.incident.status, incidents.events) == (OPEN, [])


async def test_from_telegram_only_the_recipient_can_confirm() -> None:
    incidents, confirmations = _setup()
    clock = FakeClock(T0)

    stranger = await confirm_alert(
        TOKEN,
        confirmations=confirmations,
        incidents=incidents,
        clock=clock,
        expected_destination="999",
    )
    assert (stranger.outcome, stranger.alert) == (ConfirmOutcome.NOT_YOURS, None)
    assert (incidents.incident.status, incidents.events) == (OPEN, [])
    assert confirmations.alert.used_at is None

    recipient = await confirm_alert(
        TOKEN,
        confirmations=confirmations,
        incidents=incidents,
        clock=clock,
        expected_destination="4242",
    )
    assert recipient.outcome is ConfirmOutcome.CONFIRMED
