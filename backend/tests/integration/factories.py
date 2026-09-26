"""Filas mínimas para los tests de integración. Cada llamada crea su propia organización,
así los tests no comparten datos aunque usen la misma base."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
from uuid_utils.compat import uuid7

T0 = datetime(2026, 10, 1, 8, 40, tzinfo=UTC)


@dataclass(frozen=True)
class Graph:
    organization_id: UUID
    zone_id: UUID
    station_id: UUID
    policy_id: UUID
    rule_id: UUID


async def create_organization(conn: asyncpg.Connection) -> UUID:
    org_id = uuid7()
    await conn.execute(
        "INSERT INTO core.organizations (id, keycloak_org_id, name) VALUES ($1, $2, $3)",
        org_id,
        uuid7(),
        f"org {org_id}",
    )
    return org_id


async def create_graph(conn: asyncpg.Connection) -> Graph:
    """Organización con una zona, una estación, una política y una regla."""
    org_id = await create_organization(conn)
    zone_id, station_id, policy_id, rule_id = uuid7(), uuid7(), uuid7(), uuid7()
    await conn.execute(
        """
        INSERT INTO core.risk_zones (id, organization_id, name, risk_level, geom)
        VALUES ($1, $2, 'Zona', 'high',
                ST_GeomFromText('MULTIPOLYGON(((-76.7 -11.9, -76.6 -11.9, -76.6 -12.0,
                                                -76.7 -12.0, -76.7 -11.9)))', 4326))
        """,
        zone_id,
        org_id,
    )
    await conn.execute(
        """
        INSERT INTO core.stations (id, organization_id, code, name, variable, unit, location,
                                   source, expected_interval_s, api_key_hash, api_key_rotated_at)
        VALUES ($1, $2, 'EST-1', 'Estación', 'discharge', 'm3/s',
                ST_SetSRID(ST_MakePoint(-76.65, -11.95), 4326),
                'simulator', 10, 'hash', $3)
        """,
        station_id,
        org_id,
        T0,
    )
    await conn.execute(
        "INSERT INTO core.escalation_policies (id, organization_id, name) VALUES ($1, $2, 'P')",
        policy_id,
        org_id,
    )
    await conn.execute(
        """
        INSERT INTO core.rules (id, organization_id, zone_id, station_id, type, params,
                                severity, escalation_policy_id, cooldown_s)
        VALUES ($1, $2, $3, $4, 'silence', '{}', 'critical', $5, 600)
        """,
        rule_id,
        org_id,
        zone_id,
        station_id,
        policy_id,
    )
    return Graph(org_id, zone_id, station_id, policy_id, rule_id)


async def create_incident(
    conn: asyncpg.Connection, graph: Graph, dedup_key: str | None = None
) -> UUID:
    incident_id = uuid7()
    await conn.execute(
        """
        INSERT INTO core.incidents (id, organization_id, zone_id, rule_id, station_id,
                                    severity, dedup_key, opened_at)
        VALUES ($1, $2, $3, $4, $5, 'critical', $6, $7)
        """,
        incident_id,
        graph.organization_id,
        graph.zone_id,
        graph.rule_id,
        graph.station_id,
        dedup_key or f"{graph.rule_id}:{graph.zone_id}:{graph.station_id}",
        T0,
    )
    return incident_id
