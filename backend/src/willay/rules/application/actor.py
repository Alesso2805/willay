from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Actor:
    organization_id: UUID  # the tenant: never taken from the request body
    user_id: UUID
