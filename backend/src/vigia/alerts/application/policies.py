"""Casos de uso de políticas de escalamiento (VIG-24). Solo admin; todo se audita y
filtra por la organización del actor (una política de otra organización no existe: 404).

Editar una política cambia también los incidentes en curso (SPEC): el worker lee sus
niveles al escalar. Una política que alguna regla usa no se puede borrar.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from uuid_utils.compat import uuid7

from vigia.alerts.domain.alerts import Channel
from vigia.alerts.domain.policies import (
    LevelData,
    PolicyData,
    Target,
    validate_policy,
)
from vigia.shared.audit import AuditEntry, AuditLog
from vigia.shared.clock import Clock

ENTITY_TYPE = "escalation_policy"


@dataclass(frozen=True)
class Actor:
    organization_id: UUID  # el tenant: nunca sale del cuerpo de la petición
    user_id: UUID


@dataclass(frozen=True)
class PolicyTarget:
    contact_group_id: UUID
    contact_group_name: str
    channel: Channel


@dataclass(frozen=True)
class PolicyLevel:
    level_order: int
    wait_s: int
    targets: tuple[PolicyTarget, ...]


@dataclass(frozen=True)
class Policy:
    id: UUID
    name: str
    levels: tuple[PolicyLevel, ...]
    created_at: datetime

    @property
    def data(self) -> PolicyData:
        return PolicyData(
            name=self.name,
            levels=tuple(
                LevelData(
                    level.wait_s,
                    tuple(Target(t.contact_group_id, t.channel) for t in level.targets),
                )
                for level in self.levels
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        """Lo que se guarda en la auditoría: la política completa."""
        return {
            "name": self.name,
            "levels": [
                {
                    "level_order": level.level_order,
                    "wait_s": level.wait_s,
                    "targets": [
                        {"contact_group_id": str(t.contact_group_id), "channel": t.channel.value}
                        for t in level.targets
                    ],
                }
                for level in self.levels
            ],
        }


class PolicyNotFoundError(Exception):
    pass


class DuplicatePolicyNameError(Exception):
    pass


class UnknownGroupsError(Exception):
    def __init__(self, group_ids: frozenset[UUID]) -> None:
        super().__init__(f"grupos desconocidos: {sorted(map(str, group_ids))}")
        self.group_ids = group_ids


class PolicyInUseError(Exception):
    """Alguna regla la usa: borrarla dejaría reglas sin a quién avisar."""


class PolicyRepository(Protocol):
    async def all_of(self, organization_id: UUID) -> list[Policy]: ...

    async def get(
        self, organization_id: UUID, policy_id: UUID, *, for_update: bool = False
    ) -> Policy | None: ...

    async def missing_groups(
        self, organization_id: UUID, group_ids: frozenset[UUID]
    ) -> frozenset[UUID]:
        """Los grupos que no existen en la organización (los de otra no cuentan)."""
        ...

    async def add(
        self, policy_id: UUID, organization_id: UUID, data: PolicyData, now: datetime
    ) -> Policy:
        """Lanza DuplicatePolicyNameError si el nombre ya existe en la organización."""
        ...

    async def replace(self, organization_id: UUID, policy_id: UUID, data: PolicyData) -> Policy:
        """Nombre y niveles completos; lanza DuplicatePolicyNameError."""
        ...

    async def delete(self, policy_id: UUID) -> None:
        """Lanza PolicyInUseError si alguna regla la usa."""
        ...


async def create_policy(
    actor: Actor, data: PolicyData, *, policies: PolicyRepository, audit: AuditLog, clock: Clock
) -> Policy:
    await _check(actor, data, policies)
    now = clock.now()
    policy = await policies.add(uuid7(), actor.organization_id, data, now)
    await audit.record(_entry(actor, policy.id, "create", None, policy, now))
    return policy


async def update_policy(
    actor: Actor,
    policy_id: UUID,
    data: PolicyData,
    *,
    policies: PolicyRepository,
    audit: AuditLog,
    clock: Clock,
) -> Policy:
    # FOR UPDATE: dos admins editando la misma política no se pisan el "antes" auditado.
    current = await policies.get(actor.organization_id, policy_id, for_update=True)
    if current is None:
        raise PolicyNotFoundError(policy_id)
    if current.data == data:
        return current  # sin cambios: ni escritura ni entrada de auditoría vacía
    await _check(actor, data, policies)
    updated = await policies.replace(actor.organization_id, policy_id, data)
    await audit.record(_entry(actor, policy_id, "update", current, updated, clock.now()))
    return updated


async def delete_policy(
    actor: Actor, policy_id: UUID, *, policies: PolicyRepository, audit: AuditLog, clock: Clock
) -> None:
    current = await policies.get(actor.organization_id, policy_id, for_update=True)
    if current is None:
        raise PolicyNotFoundError(policy_id)
    await policies.delete(policy_id)
    await audit.record(_entry(actor, policy_id, "delete", current, None, clock.now()))


async def _check(actor: Actor, data: PolicyData, policies: PolicyRepository) -> None:
    validate_policy(data)
    missing = await policies.missing_groups(actor.organization_id, data.group_ids)
    if missing:
        raise UnknownGroupsError(missing)


def _entry(
    actor: Actor,
    policy_id: UUID,
    action: str,
    before: Policy | None,
    after: Policy | None,
    at: datetime,
) -> AuditEntry:
    return AuditEntry(
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
        entity_type=ENTITY_TYPE,
        entity_id=policy_id,
        action=action,
        before=before.snapshot() if before is not None else None,
        after=after.snapshot() if after is not None else None,
        at=at,
    )
