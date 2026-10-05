"""VIG-44: the organization's language and time zone, validated and audited."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from willay.identity.application.organization import Organization, update_organization
from willay.identity.domain.organization import (
    InvalidOrganizationError,
    OrganizationSettings,
    validate_settings,
)
from willay.shared.audit import AuditEntry
from willay.shared.clock import FakeClock
from willay.shared.errors import ErrorCode
from willay.shared.languages import Language

T0 = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
ORG = uuid4()
USER = uuid4()


@pytest.mark.parametrize("timezone", ["America/Lima", "Europe/Madrid", "UTC"])
def test_an_iana_time_zone_is_accepted(timezone: str) -> None:
    validate_settings(OrganizationSettings(Language.ES, timezone))


@pytest.mark.parametrize("timezone", ["-05:00", "GMT-5", "Mars/Olympus", "america/lima", ""])
def test_anything_else_is_refused_with_its_code(timezone: str) -> None:
    with pytest.raises(InvalidOrganizationError) as caught:
        validate_settings(OrganizationSettings(Language.ES, timezone))
    assert caught.value.field == "timezone"
    assert caught.value.code is ErrorCode.ORGANIZATION_TIMEZONE_UNKNOWN
    assert caught.value.params == {"timezone": timezone}


class Organizations:
    def __init__(self) -> None:
        self.organization = Organization(ORG, "Demo Rímac", Language.ES, "America/Lima")
        self.locked = False

    async def get(self, organization_id: UUID, *, for_update: bool = False) -> Organization:
        assert organization_id == ORG
        self.locked = for_update
        return self.organization

    async def update(self, organization_id: UUID, settings: OrganizationSettings) -> None:
        self.organization = Organization(ORG, "Demo Rímac", settings.language, settings.timezone)


class Audit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


async def _update(organizations: Organizations, audit: Audit, timezone: str) -> Organization:
    return await update_organization(
        ORG,
        USER,
        OrganizationSettings(Language.EN, timezone),
        organizations=organizations,
        audit=audit,
        clock=FakeClock(T0),
    )


async def test_a_change_is_saved_and_audited_with_both_sides() -> None:
    organizations, audit = Organizations(), Audit()
    updated = await _update(organizations, audit, "America/Bogota")

    assert (updated.language, updated.timezone) == (Language.EN, "America/Bogota")
    assert organizations.locked  # read with FOR UPDATE: two admins do not overwrite each other
    [entry] = audit.entries
    assert (entry.entity_type, entry.action, entry.actor_id, entry.at) == (
        "organization",
        "update",
        USER,
        T0,
    )
    assert entry.before == {"name": "Demo Rímac", "language": "es", "timezone": "America/Lima"}
    assert entry.after == {"name": "Demo Rímac", "language": "en", "timezone": "America/Bogota"}


async def test_saving_the_same_settings_audits_nothing() -> None:
    organizations, audit = Organizations(), Audit()
    organizations.organization = Organization(ORG, "Demo Rímac", Language.EN, "America/Lima")
    await _update(organizations, audit, "America/Lima")
    assert audit.entries == []


async def test_an_unknown_time_zone_changes_nothing() -> None:
    organizations, audit = Organizations(), Audit()
    with pytest.raises(InvalidOrganizationError):
        await _update(organizations, audit, "-05:00")
    assert organizations.organization.timezone == "America/Lima"
    assert audit.entries == []
