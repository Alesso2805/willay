"""Contact groups: who a policy level notifies. A group may name the zone it covers;
that zone is a label for the admin, alerting does not depend on it.
"""

from dataclasses import dataclass
from uuid import UUID

from willay.shared.errors import ErrorCode, FieldError

MAX_NAME_LENGTH = 120


@dataclass(frozen=True)
class GroupData:
    name: str
    zone_id: UUID | None
    member_ids: frozenset[UUID]


class InvalidGroupError(FieldError, ValueError):
    pass


def validate_group(data: GroupData) -> None:
    if not data.name or len(data.name) > MAX_NAME_LENGTH:
        raise InvalidGroupError("name", ErrorCode.GROUP_NAME_LENGTH, max=MAX_NAME_LENGTH)
