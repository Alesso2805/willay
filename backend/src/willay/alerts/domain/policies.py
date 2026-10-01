"""Escalation policies (VIG-24): ordered levels that notify contact groups through a channel.

Levels are given as a list and their order is their position (1, 2, 3...), so there are no
gaps or duplicate orders to validate.
"""

from dataclasses import dataclass
from uuid import UUID

from willay.alerts.domain.alerts import Channel

MAX_NAME_LENGTH = 120
MAX_LEVELS = 10
MAX_WAIT_S = 86_400  # one day: waiting longer is not escalating, it is forgetting


class InvalidPolicyError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    contact_group_id: UUID
    channel: Channel


@dataclass(frozen=True)
class LevelData:
    wait_s: int
    targets: tuple[Target, ...]


@dataclass(frozen=True)
class PolicyData:
    name: str
    levels: tuple[LevelData, ...]

    @property
    def group_ids(self) -> frozenset[UUID]:
        return frozenset(t.contact_group_id for level in self.levels for t in level.targets)


def validate_policy(data: PolicyData) -> None:
    if not data.name.strip() or len(data.name) > MAX_NAME_LENGTH:
        raise InvalidPolicyError(f"el nombre debe tener entre 1 y {MAX_NAME_LENGTH} caracteres")
    if not 1 <= len(data.levels) <= MAX_LEVELS:
        raise InvalidPolicyError(f"una política tiene entre 1 y {MAX_LEVELS} niveles")
    for order, level in enumerate(data.levels, start=1):
        if not 1 <= level.wait_s <= MAX_WAIT_S:
            raise InvalidPolicyError(f"nivel {order}: la espera va de 1 a {MAX_WAIT_S} segundos")
        # A level without targets would escalate immediately: it would be useless.
        if not level.targets:
            raise InvalidPolicyError(f"nivel {order}: necesita al menos un grupo destino")
        if len(set(level.targets)) != len(level.targets):
            raise InvalidPolicyError(f"nivel {order}: el mismo grupo y canal aparece dos veces")
