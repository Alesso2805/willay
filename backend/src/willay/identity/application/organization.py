"""Reading and changing the organization's settings, audited like every other change.

The change applies from the next message and the next page: emails, Telegram and the dashboard
read the organization's time zone each time, and contacts without a language of their own read
its language each time too (COALESCE in the message query).
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from willay.identity.domain.organization import OrganizationSettings, validate_settings
from willay.shared.audit import AuditEntry, AuditLog
from willay.shared.clock import Clock
from willay.shared.languages import Language

ENTITY_TYPE = "organization"


@dataclass(frozen=True)
class Organization:
    id: UUID
    name: str
    language: Language
    timezone: str


class OrganizationRepository(Protocol):
    async def get(self, organization_id: UUID, *, for_update: bool = False) -> Organization: ...

    async def update(self, organization_id: UUID, settings: OrganizationSettings) -> None: ...


async def update_organization(
    organization_id: UUID,
    user_id: UUID,
    settings: OrganizationSettings,
    *,
    organizations: OrganizationRepository,
    audit: AuditLog,
    clock: Clock,
) -> Organization:
    validate_settings(settings)
    before = await organizations.get(organization_id, for_update=True)
    after = Organization(before.id, before.name, settings.language, settings.timezone)
    if after == before:
        return before  # nothing changed: nothing to audit
    await organizations.update(organization_id, settings)
    await audit.record(
        AuditEntry(
            organization_id=organization_id,
            actor_id=user_id,
            entity_type=ENTITY_TYPE,
            entity_id=organization_id,
            action="update",
            before=_snapshot(before),
            after=_snapshot(after),
            at=clock.now(),
        )
    )
    return after


def _snapshot(organization: Organization) -> dict[str, str]:
    return {
        "name": organization.name,
        "language": organization.language.value,
        "timezone": organization.timezone,
    }
