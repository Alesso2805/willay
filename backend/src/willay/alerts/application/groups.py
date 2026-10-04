"""Contact group use cases (VIG-36). Admin only, audited in the same transaction and scoped to
the actor's organization (another organization's group, zone or contact does not exist).

A group that a policy notifies is not deleted (SPEC): the policy would lose a target without
anyone noticing. The admin first takes it out of those policies; the error names them.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from willay.alerts.application.policies import Actor
from willay.alerts.domain.groups import GroupData, InvalidGroupError, validate_group
from willay.shared.audit import AuditEntry, AuditLog
from willay.shared.clock import Clock
from willay.shared.errors import ErrorCode

ENTITY_TYPE = "contact_group"


@dataclass(frozen=True)
class Ref:
    id: UUID
    name: str


@dataclass(frozen=True)
class ContactGroup:
    id: UUID
    name: str
    zone: Ref | None
    members: tuple[Ref, ...]  # contacts, by name
    policies: tuple[Ref, ...]  # the policies that notify it, by name

    @property
    def data(self) -> GroupData:
        return GroupData(
            self.name,
            self.zone.id if self.zone is not None else None,
            frozenset(m.id for m in self.members),
        )

    def snapshot(self) -> dict[str, Any]:
        """What the audit log stores, readable as it was then."""
        return {
            "name": self.name,
            "zone": self.zone.name if self.zone is not None else None,
            "members": [member.name for member in self.members],
        }


class GroupNotFoundError(Exception):
    pass


class DuplicateGroupNameError(Exception):
    pass


class GroupInUseError(Exception):
    def __init__(self, group: ContactGroup) -> None:
        super().__init__(group.name)
        self.group = group


class GroupRepository(Protocol):
    async def all_of(self, organization_id: UUID) -> list[ContactGroup]:
        """By name."""
        ...

    async def get(
        self, organization_id: UUID, group_id: UUID, *, for_update: bool = False
    ) -> ContactGroup | None: ...

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool: ...

    async def missing_contacts(
        self, organization_id: UUID, contact_ids: frozenset[UUID]
    ) -> frozenset[UUID]:
        """Contacts that do not exist in the organization (another organization's don't count)."""
        ...

    async def add(self, group_id: UUID, organization_id: UUID, data: GroupData) -> ContactGroup:
        """Raises DuplicateGroupNameError if the name already exists in the organization."""
        ...

    async def replace(self, organization_id: UUID, group_id: UUID, data: GroupData) -> ContactGroup:
        """Replaces name, zone and the whole member list; raises DuplicateGroupNameError."""
        ...

    async def delete(self, organization_id: UUID, group_id: UUID) -> None:
        """Its memberships go with it. Raises GroupInUseError if a policy started using it."""
        ...


async def create_group(
    actor: Actor, data: GroupData, *, groups: GroupRepository, audit: AuditLog, clock: Clock
) -> ContactGroup:
    await _check(actor, data, groups)
    group = await groups.add(uuid7(), actor.organization_id, data)
    await audit.record(_entry(actor, group.id, "create", None, group, clock.now()))
    return group


async def update_group(
    actor: Actor,
    group_id: UUID,
    data: GroupData,
    *,
    groups: GroupRepository,
    audit: AuditLog,
    clock: Clock,
) -> ContactGroup:
    current = await _locked(actor, group_id, groups)
    if current.data == data:
        return current  # no changes: no write and no empty audit entry
    await _check(actor, data, groups)
    updated = await groups.replace(actor.organization_id, group_id, data)
    await audit.record(_entry(actor, group_id, "update", current, updated, clock.now()))
    return updated


async def delete_group(
    actor: Actor, group_id: UUID, *, groups: GroupRepository, audit: AuditLog, clock: Clock
) -> None:
    current = await _locked(actor, group_id, groups)
    if current.policies:
        raise GroupInUseError(current)
    await groups.delete(actor.organization_id, group_id)
    await audit.record(_entry(actor, group_id, "delete", current, None, clock.now()))


async def _check(actor: Actor, data: GroupData, groups: GroupRepository) -> None:
    validate_group(data)
    if data.zone_id is not None and not await groups.zone_exists(
        actor.organization_id, data.zone_id
    ):
        raise InvalidGroupError("zone_id", ErrorCode.GROUP_ZONE_UNKNOWN)
    if await groups.missing_contacts(actor.organization_id, data.member_ids):
        raise InvalidGroupError("member_ids", ErrorCode.GROUP_MEMBER_UNKNOWN)


async def _locked(actor: Actor, group_id: UUID, groups: GroupRepository) -> ContactGroup:
    # FOR UPDATE: two admins acting on the same group don't clobber the audited "before".
    group = await groups.get(actor.organization_id, group_id, for_update=True)
    if group is None:
        raise GroupNotFoundError(group_id)
    return group


def _entry(
    actor: Actor,
    group_id: UUID,
    action: str,
    before: ContactGroup | None,
    after: ContactGroup | None,
    at: datetime,
) -> AuditEntry:
    return AuditEntry(
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
        entity_type=ENTITY_TYPE,
        entity_id=group_id,
        action=action,
        before=before.snapshot() if before is not None else None,
        after=after.snapshot() if after is not None else None,
        at=at,
    )
