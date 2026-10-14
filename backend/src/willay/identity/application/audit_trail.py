"""Audit log pages for the admin (VIG-38). Always the actor's organization only."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from willay.identity.domain.audit_trail import Cursor, EntityType, encode_cursor


@dataclass(frozen=True)
class AuditFilters:
    entity_type: EntityType | None = None
    entity_id: UUID | None = None
    actor_id: UUID | None = None
    since: datetime | None = None  # inclusive
    until: datetime | None = None  # exclusive


@dataclass(frozen=True)
class AuditRecord:
    id: int
    at: datetime
    # None: nobody from the organization, e.g. the contact themselves linking Telegram.
    actor_id: UUID | None
    actor_name: str | None
    entity_type: str
    entity_id: UUID
    entity_name: str | None  # its current name; None once deleted, and for rules and the
    # organization, whose name is not looked up
    action: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None


@dataclass(frozen=True)
class Author:
    id: UUID
    name: str


@dataclass(frozen=True)
class AuditPage:
    records: list[AuditRecord]
    next_cursor: str | None  # None: this was the last page


class AuditTrail(Protocol):
    async def page(
        self, organization_id: UUID, filters: AuditFilters, after: Cursor | None, limit: int
    ) -> list[AuditRecord]:
        """Most recent first, strictly older than `after`."""
        ...

    async def authors(self, organization_id: UUID) -> list[Author]:
        """Users who appear in the log, by name."""
        ...


async def read_page(
    organization_id: UUID,
    filters: AuditFilters,
    after: Cursor | None,
    limit: int,
    *,
    trail: AuditTrail,
) -> AuditPage:
    # One more than asked: whether it comes back says if there is a next page.
    records = await trail.page(organization_id, filters, after, limit + 1)
    if len(records) <= limit:
        return AuditPage(records, None)
    last = records[limit - 1]
    return AuditPage(records[:limit], encode_cursor(Cursor(last.at, last.id)))
