"""PolicyRepository over core.escalation_policies, their levels and targets."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

from willay.alerts.application.policies import (
    DuplicatePolicyNameError,
    Policy,
    PolicyInUseError,
    PolicyLevel,
    PolicyTarget,
)
from willay.alerts.domain.alerts import Channel
from willay.alerts.domain.policies import PolicyData

_UNIQUE_NAME = "escalation_policies_organization_id_name_key"
_USED_BY_RULES = "rules_escalation_policy_id_fkey"

# One row per target; LEFT JOIN keeps a policy without levels (the API cannot create one,
# but a seed or a migration could).
_SELECT = """
    SELECT p.id, p.name, p.created_at, l.level_order, l.wait_s,
           t.contact_group_id, g.name AS group_name, t.channel
    FROM core.escalation_policies p
    LEFT JOIN core.escalation_levels l ON l.policy_id = p.id
    LEFT JOIN core.level_targets t ON t.level_id = l.id
    LEFT JOIN core.contact_groups g ON g.id = t.contact_group_id
    WHERE p.organization_id = :organization_id
"""
_ORDER = " ORDER BY p.name, p.id, l.level_order, g.name, t.channel"

_ALL = text(_SELECT + _ORDER)
_ONE = text(_SELECT + " AND p.id = :id" + _ORDER)
_LOCK = text("""
    SELECT id FROM core.escalation_policies
    WHERE organization_id = :organization_id AND id = :id
    FOR UPDATE
""")
_KNOWN_GROUPS = text("""
    SELECT id FROM core.contact_groups
    WHERE organization_id = :organization_id AND id = ANY(CAST(:ids AS uuid[]))
""")
_INSERT_POLICY = text("""
    INSERT INTO core.escalation_policies (id, organization_id, name, created_at)
    VALUES (:id, :organization_id, :name, :now)
""")
_RENAME = text("UPDATE core.escalation_policies SET name = :name WHERE id = :id")
# Targets are deleted by cascade along with their levels.
_DROP_LEVELS = text("DELETE FROM core.escalation_levels WHERE policy_id = :id")
_INSERT_LEVEL = text("""
    INSERT INTO core.escalation_levels (id, policy_id, level_order, wait_s)
    VALUES (:id, :policy_id, :level_order, :wait_s)
""")
_INSERT_TARGET = text("""
    INSERT INTO core.level_targets (id, level_id, contact_group_id, channel)
    VALUES (:id, :level_id, :contact_group_id, :channel)
""")
_DELETE = text("DELETE FROM core.escalation_policies WHERE id = :id")


class SqlPolicyRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def all_of(self, organization_id: UUID) -> list[Policy]:
        rows = await self._conn.execute(_ALL, {"organization_id": organization_id})
        return _policies(rows.all())

    async def get(
        self, organization_id: UUID, policy_id: UUID, *, for_update: bool = False
    ) -> Policy | None:
        params = {"organization_id": organization_id, "id": policy_id}
        if for_update and await self._conn.scalar(_LOCK, params) is None:
            return None
        policies = _policies((await self._conn.execute(_ONE, params)).all())
        return policies[0] if policies else None

    async def missing_groups(
        self, organization_id: UUID, group_ids: frozenset[UUID]
    ) -> frozenset[UUID]:
        rows = await self._conn.execute(
            _KNOWN_GROUPS,
            {"organization_id": organization_id, "ids": [str(g) for g in group_ids]},
        )
        return group_ids - {r.id for r in rows}

    async def add(
        self, policy_id: UUID, organization_id: UUID, data: PolicyData, now: datetime
    ) -> Policy:
        params = {"id": policy_id, "organization_id": organization_id, "name": data.name}
        await self._with_unique_name(_INSERT_POLICY, params | {"now": now}, data.name)
        await self._insert_levels(policy_id, data)
        return await self._reload(organization_id, policy_id)

    async def replace(self, organization_id: UUID, policy_id: UUID, data: PolicyData) -> Policy:
        await self._with_unique_name(_RENAME, {"id": policy_id, "name": data.name}, data.name)
        await self._conn.execute(_DROP_LEVELS, {"id": policy_id})
        await self._insert_levels(policy_id, data)
        return await self._reload(organization_id, policy_id)

    async def delete(self, policy_id: UUID) -> None:
        try:
            # SAVEPOINT: if a rule uses it, the FK blocks it without aborting the request.
            # It is the only guarantee if someone creates a rule with it concurrently.
            async with self._conn.begin_nested():
                await self._conn.execute(_DELETE, {"id": policy_id})
        except IntegrityError as exc:
            if _USED_BY_RULES in str(exc.orig):
                raise PolicyInUseError(policy_id) from exc
            raise

    async def _with_unique_name(self, statement: Any, params: dict[str, Any], name: str) -> None:
        try:
            async with self._conn.begin_nested():
                await self._conn.execute(statement, params)
        except IntegrityError as exc:
            # Only this constraint means "duplicate name"; any other is propagated.
            if _UNIQUE_NAME in str(exc.orig):
                raise DuplicatePolicyNameError(name) from exc
            raise

    async def _insert_levels(self, policy_id: UUID, data: PolicyData) -> None:
        for order, level in enumerate(data.levels, start=1):
            level_id = uuid7()
            await self._conn.execute(
                _INSERT_LEVEL,
                {
                    "id": level_id,
                    "policy_id": policy_id,
                    "level_order": order,
                    "wait_s": level.wait_s,
                },
            )
            for target in level.targets:
                await self._conn.execute(
                    _INSERT_TARGET,
                    {
                        "id": uuid7(),
                        "level_id": level_id,
                        "contact_group_id": target.contact_group_id,
                        "channel": target.channel.value,
                    },
                )

    async def _reload(self, organization_id: UUID, policy_id: UUID) -> Policy:
        policy = await self.get(organization_id, policy_id)
        if policy is None:  # impossible within the same transaction
            raise LookupError(policy_id)
        return policy


def _policies(rows: Sequence[Row[Any]]) -> list[Policy]:
    """Groups the rows (one per target) into policies with their levels, in order."""
    policies: dict[UUID, tuple[str, datetime, dict[int, tuple[int, list[PolicyTarget]]]]] = {}
    for r in rows:
        _, _, levels = policies.setdefault(r.id, (r.name, r.created_at, {}))
        if r.level_order is None:
            continue
        _, targets = levels.setdefault(r.level_order, (r.wait_s, []))
        if r.contact_group_id is not None:
            targets.append(PolicyTarget(r.contact_group_id, r.group_name, Channel(r.channel)))
    return [
        Policy(
            id=policy_id,
            name=name,
            created_at=created_at,
            levels=tuple(
                PolicyLevel(order, wait_s, tuple(targets))
                for order, (wait_s, targets) in sorted(levels.items())
            ),
        )
        for policy_id, (name, created_at, levels) in policies.items()
    ]
