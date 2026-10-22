"""GroupRepository over core.contact_groups and their members."""

from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.alerts.application.groups import (
    ContactGroup,
    DuplicateGroupNameError,
    GroupInUseError,
    Ref,
)
from willay.alerts.domain.groups import GroupData

_UNIQUE_NAME = "contact_groups_organization_id_name_key"
_USED_BY_POLICIES = "level_targets_contact_group_id_fkey"

_SELECT = """
    SELECT g.id, g.name, z.id AS zone_id, z.name AS zone_name,
           COALESCE((SELECT jsonb_agg(jsonb_build_object('id', c.id, 'name', c.full_name)
                                      ORDER BY c.full_name, c.id)
                     FROM core.contact_group_members m
                     JOIN core.contacts c ON c.id = m.contact_id
                     WHERE m.group_id = g.id), '[]'::jsonb) AS members,
           COALESCE((SELECT jsonb_agg(DISTINCT jsonb_build_object('id', p.id, 'name', p.name))
                     FROM core.level_targets t
                     JOIN core.escalation_levels l ON l.id = t.level_id
                     JOIN core.escalation_policies p ON p.id = l.policy_id
                     WHERE t.contact_group_id = g.id), '[]'::jsonb) AS policies
    FROM core.contact_groups g
    LEFT JOIN core.risk_zones z ON z.id = g.zone_id
"""

_ALL = text(_SELECT + " WHERE g.organization_id = :organization_id ORDER BY g.name, g.id")
_GET = text(_SELECT + " WHERE g.organization_id = :organization_id AND g.id = :id")
_GET_FOR_UPDATE = text(
    _SELECT + " WHERE g.organization_id = :organization_id AND g.id = :id FOR UPDATE OF g"
)

_ZONE_EXISTS = text("""
    SELECT EXISTS (SELECT 1 FROM core.risk_zones
                   WHERE organization_id = :organization_id AND id = :id)
""")
_KNOWN_CONTACTS = text("""
    SELECT id FROM core.contacts
    WHERE organization_id = :organization_id AND id = ANY(CAST(:ids AS uuid[]))
""")

_ADD = text("""
    INSERT INTO core.contact_groups (id, organization_id, name, zone_id)
    VALUES (:id, :organization_id, :name, :zone_id)
""")
_REPLACE = text("""
    UPDATE core.contact_groups SET name = :name, zone_id = :zone_id
    WHERE organization_id = :organization_id AND id = :id
""")
_DROP_MEMBERS = text("DELETE FROM core.contact_group_members WHERE group_id = :id")
_ADD_MEMBERS = text("""
    INSERT INTO core.contact_group_members (group_id, contact_id)
    SELECT :id, unnest(CAST(:contact_ids AS uuid[]))
""")
_DELETE = text("DELETE FROM core.contact_groups WHERE id = :id")  # memberships cascade


class SqlGroupRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def all_of(self, organization_id: UUID) -> list[ContactGroup]:
        rows = await self._conn.execute(_ALL, {"organization_id": organization_id})
        return [_group(r) for r in rows]

    async def get(
        self, organization_id: UUID, group_id: UUID, *, for_update: bool = False
    ) -> ContactGroup | None:
        query = _GET_FOR_UPDATE if for_update else _GET
        row = (
            await self._conn.execute(query, {"organization_id": organization_id, "id": group_id})
        ).first()
        return _group(row) if row is not None else None

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool:
        params = {"organization_id": organization_id, "id": zone_id}
        return bool(await self._conn.scalar(_ZONE_EXISTS, params))

    async def missing_contacts(
        self, organization_id: UUID, contact_ids: frozenset[UUID]
    ) -> frozenset[UUID]:
        if not contact_ids:
            return frozenset()
        rows = await self._conn.execute(
            _KNOWN_CONTACTS,
            {"organization_id": organization_id, "ids": [str(c) for c in contact_ids]},
        )
        return contact_ids - {r.id for r in rows}

    async def add(self, group_id: UUID, organization_id: UUID, data: GroupData) -> ContactGroup:
        params = {"id": group_id, "organization_id": organization_id}
        await self._with_unique_name(_ADD, params | _columns(data), data.name)
        await self._set_members(group_id, data)
        return await self._reload(organization_id, group_id)

    async def replace(self, organization_id: UUID, group_id: UUID, data: GroupData) -> ContactGroup:
        params = {"id": group_id, "organization_id": organization_id}
        await self._with_unique_name(_REPLACE, params | _columns(data), data.name)
        await self._conn.execute(_DROP_MEMBERS, {"id": group_id})
        await self._set_members(group_id, data)
        return await self._reload(organization_id, group_id)

    async def delete(self, organization_id: UUID, group_id: UUID) -> None:
        try:
            # SAVEPOINT: if a policy started using it after the check, the FK refuses the
            # delete without aborting the request, and the error names that policy too.
            async with self._conn.begin_nested():
                await self._conn.execute(_DELETE, {"id": group_id})
        except IntegrityError as exc:
            if _USED_BY_POLICIES in str(exc.orig):
                raise GroupInUseError(await self._reload(organization_id, group_id)) from exc
            raise

    async def _set_members(self, group_id: UUID, data: GroupData) -> None:
        if data.member_ids:
            ids = [str(c) for c in data.member_ids]
            await self._conn.execute(_ADD_MEMBERS, {"id": group_id, "contact_ids": ids})

    async def _with_unique_name(self, statement: Any, params: dict[str, Any], name: str) -> None:
        try:
            async with self._conn.begin_nested():
                await self._conn.execute(statement, params)
        except IntegrityError as exc:
            # Only this constraint means "duplicate name"; any other is propagated.
            if _UNIQUE_NAME in str(exc.orig):
                raise DuplicateGroupNameError(name) from exc
            raise

    async def _reload(self, organization_id: UUID, group_id: UUID) -> ContactGroup:
        group = await self.get(organization_id, group_id)
        if group is None:  # impossible within the same transaction
            raise LookupError(group_id)
        return group


def _columns(data: GroupData) -> dict[str, Any]:
    return {"name": data.name, "zone_id": data.zone_id}


def _group(r: Row[Any]) -> ContactGroup:
    return ContactGroup(
        id=r.id,
        name=r.name,
        zone=Ref(r.zone_id, r.zone_name) if r.zone_id is not None else None,
        members=tuple(Ref(UUID(m["id"]), m["name"]) for m in r.members),
        policies=tuple(
            sorted((Ref(UUID(p["id"]), p["name"]) for p in r.policies), key=lambda p: p.name)
        ),
    )
