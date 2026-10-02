"""Contact groups (VIG-36): who a policy level notifies. A group may name the zone it covers;
that zone is a label for the admin, alerting does not depend on it.
"""

from dataclasses import dataclass
from uuid import UUID

MAX_NAME_LENGTH = 120


@dataclass(frozen=True)
class GroupData:
    name: str
    zone_id: UUID | None
    member_ids: frozenset[UUID]


class InvalidGroupError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def validate_group(data: GroupData) -> None:
    if not data.name or len(data.name) > MAX_NAME_LENGTH:
        raise InvalidGroupError(
            "name", f"El nombre debe tener entre 1 y {MAX_NAME_LENGTH} caracteres."
        )
