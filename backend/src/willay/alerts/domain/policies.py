"""Escalation policies (VIG-24): ordered levels that notify contact groups through a channel.

Levels are given as a list and their order is their position (1, 2, 3...), so there are no
gaps or duplicate orders to validate.
"""

from dataclasses import dataclass
from uuid import UUID

from willay.alerts.domain.alerts import Channel
from willay.shared.errors import CodedError, ErrorCode

MAX_NAME_LENGTH = 120
MAX_LEVELS = 10
MAX_WAIT_S = 86_400  # one day: waiting longer is not escalating, it is forgetting


class InvalidPolicyError(CodedError):
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
        raise InvalidPolicyError(ErrorCode.POLICY_NAME_LENGTH, max=MAX_NAME_LENGTH)
    if not 1 <= len(data.levels) <= MAX_LEVELS:
        raise InvalidPolicyError(ErrorCode.POLICY_LEVEL_COUNT, max=MAX_LEVELS)
    for order, level in enumerate(data.levels, start=1):
        if not 1 <= level.wait_s <= MAX_WAIT_S:
            raise InvalidPolicyError(ErrorCode.POLICY_LEVEL_WAIT, level=order, max=MAX_WAIT_S)
        # A level without targets would escalate immediately: it would be useless.
        if not level.targets:
            raise InvalidPolicyError(ErrorCode.POLICY_LEVEL_NO_TARGET, level=order)
        if len(set(level.targets)) != len(level.targets):
            raise InvalidPolicyError(ErrorCode.POLICY_LEVEL_REPEATED_TARGET, level=order)
