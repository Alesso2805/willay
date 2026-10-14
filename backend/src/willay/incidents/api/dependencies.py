"""What other modules' APIs may use from incidents, without reaching into its infrastructure."""

from typing import Annotated

from fastapi import Depends

from willay.incidents.application.lifecycle import IncidentRepository
from willay.incidents.infrastructure.incidents_repository import SqlIncidentRepository
from willay.shared.web import DbConnection


def get_incident_repository(conn: DbConnection) -> IncidentRepository:
    """On the request's connection, so it shares the endpoint's transaction."""
    return SqlIncidentRepository(conn)


IncidentRepositoryDep = Annotated[IncidentRepository, Depends(get_incident_repository)]
