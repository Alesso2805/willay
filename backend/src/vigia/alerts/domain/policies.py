"""Políticas de escalamiento (VIG-24): niveles ordenados que notifican a grupos por un canal.

Los niveles se dan como lista y su orden es su posición (1, 2, 3...): así no hay huecos ni
órdenes repetidos que validar. Cada nivel espera `wait_s` desde que se le avisa antes de
escalar al siguiente.
"""

from dataclasses import dataclass
from uuid import UUID

from vigia.alerts.domain.alerts import Channel

MAX_NAME_LENGTH = 120
MAX_LEVELS = 10
MAX_WAIT_S = 86_400  # un día: esperar más no es escalar, es olvidar el incidente


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
        # Un nivel sin destinos escalaría en el acto: no sirve de nada tenerlo.
        if not level.targets:
            raise InvalidPolicyError(f"nivel {order}: necesita al menos un grupo destino")
        if len(set(level.targets)) != len(level.targets):
            raise InvalidPolicyError(f"nivel {order}: el mismo grupo y canal aparece dos veces")
