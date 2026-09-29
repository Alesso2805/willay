"""Consultas SQL del evaluador: reglas aplicables e historial de lecturas."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.incidents.domain.incidents import EvidenceReading
from vigia.rules.application.rule_evaluator import ApplicableRule

# El JOIN con zone_stations es lo que hace que una estación sin zona nunca alerte, y el
# filtro por organización es una defensa más: nunca se evalúa con reglas de otro tenant.
_APPLICABLE = text("""
    SELECT r.id, r.organization_id, r.zone_id, r.type, r.params, r.severity
    FROM core.rules r
    JOIN core.risk_zones z ON z.id = r.zone_id AND z.is_active
    JOIN core.zone_stations zs ON zs.zone_id = r.zone_id AND zs.station_id = :station_id
    WHERE r.is_active
      AND r.organization_id = :organization_id
      AND r.type IN ('threshold', 'rate_of_change')
      AND (r.station_id IS NULL OR r.station_id = :station_id)
    ORDER BY r.id
""")

# Solo lecturas `ok`: las tardías nunca entran en las ventanas de las reglas (SPEC).
_LATEST_OK = text("""
    SELECT measured_at, value FROM ingest.readings
    WHERE station_id = :station_id AND quality = 'ok' AND measured_at <= :until
    ORDER BY measured_at DESC
    LIMIT :limit
""")


class SqlRuleRepository:
    async def applicable(
        self, tx: AsyncConnection, organization_id: UUID, station_id: UUID
    ) -> list[ApplicableRule]:
        rows = await tx.execute(
            _APPLICABLE, {"organization_id": organization_id, "station_id": station_id}
        )
        return [
            ApplicableRule(r.id, r.organization_id, r.zone_id, r.type, r.params, r.severity)
            for r in rows
        ]


class SqlReadingHistory:
    async def latest_ok(
        self, tx: AsyncConnection, station_id: UUID, until: datetime, limit: int
    ) -> list[EvidenceReading]:
        rows = await tx.execute(
            _LATEST_OK, {"station_id": station_id, "until": until, "limit": limit}
        )
        return [EvidenceReading(r.measured_at, r.value) for r in rows]
