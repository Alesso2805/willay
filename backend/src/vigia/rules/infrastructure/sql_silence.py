"""Consultas del worker silence: estaciones vigiladas y estaciones que volvieron."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.incidents.application.station_recovery import Recovery
from vigia.rules.application.silence_check import WatchedStation

# Parte de las reglas de silencio activas (SPEC), no de las estaciones. El JOIN con
# zone_stations deja fuera a las estaciones sin zona y el LEFT JOIN con los latidos
# conserva a las que nunca reportaron: decidir qué hacer con ellas es del dominio.
_WATCHED = text("""
    SELECT r.id AS rule_id, r.organization_id, r.zone_id, r.params, r.severity,
           s.id AS station_id, s.expected_interval_s, s.silence_multiplier,
           h.last_seen_at, h.last_measured_at, h.last_value
    FROM core.rules r
    JOIN core.risk_zones z ON z.id = r.zone_id AND z.is_active
    JOIN core.zone_stations zs ON zs.zone_id = r.zone_id
    JOIN core.stations s ON s.id = zs.station_id
                        AND s.organization_id = r.organization_id
                        AND s.status = 'active'
    LEFT JOIN ingest.station_heartbeats h ON h.station_id = s.id
    WHERE r.is_active
      AND r.type = 'silence'
      AND (r.station_id IS NULL OR r.station_id = s.id)
    ORDER BY r.id, s.id
""")

# "Volvió a reportar": su latido es posterior al que se conocía al abrir el incidente
# (details.last_seen_at del evento opened). Compararlo con opened_at no basta: un lote
# recibido justo antes de abrir, pero confirmado después de leer los latidos, quedaría
# fuera para siempre. El NOT EXISTS solo evita trabajo; la unicidad la da el índice 0005.
_RECOVERIES = text("""
    SELECT i.id AS incident_id, i.organization_id, i.station_id,
           h.last_seen_at, h.last_measured_at, h.last_value
    FROM core.incidents i
    JOIN core.rules r ON r.id = i.rule_id AND r.type = 'silence'
    JOIN core.incident_events o ON o.incident_id = i.id AND o.event_type = 'opened'
    JOIN ingest.station_heartbeats h ON h.station_id = i.station_id
    WHERE i.status IN ('open', 'acknowledged')
      AND h.last_seen_at > COALESCE(CAST(o.payload->'details'->>'last_seen_at' AS timestamptz),
                                    i.opened_at)
      AND NOT EXISTS (SELECT 1 FROM core.incident_events e
                      WHERE e.incident_id = i.id AND e.event_type = 'station_recovered')
    ORDER BY i.id
""")


class SqlSilenceRepository:
    async def watched(self, tx: AsyncConnection) -> list[WatchedStation]:
        rows = await tx.execute(_WATCHED)
        return [
            WatchedStation(
                rule_id=r.rule_id,
                organization_id=r.organization_id,
                zone_id=r.zone_id,
                rule_params=r.params,
                severity=r.severity,
                station_id=r.station_id,
                expected_interval_s=r.expected_interval_s,
                silence_multiplier=r.silence_multiplier,
                last_seen_at=r.last_seen_at,
                last_measured_at=r.last_measured_at,
                last_value=r.last_value,
            )
            for r in rows
        ]

    async def recoveries(self, tx: AsyncConnection) -> list[Recovery]:
        rows = await tx.execute(_RECOVERIES)
        return [
            Recovery(
                incident_id=r.incident_id,
                organization_id=r.organization_id,
                station_id=r.station_id,
                last_seen_at=r.last_seen_at,
                last_measured_at=r.last_measured_at,
                last_value=r.last_value,
            )
            for r in rows
        ]
