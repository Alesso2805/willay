"""Filas mínimas para los tests de integración. Cada llamada crea su propia organización,
así los tests no comparten datos aunque usen la misma base."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
from argon2 import PasswordHasher
from uuid_utils.compat import uuid7

from vigia.ingestion.domain.api_keys import generate_api_key
from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher

T0 = datetime(2026, 10, 1, 8, 40, tzinfo=UTC)
# Parámetros mínimos de Argon2id: los tests ejercitan el flujo, no el costo del hash.
FAST_HASHER = ApiKeyHasher(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


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


async def create_station_with_key(conn: asyncpg.Connection) -> tuple[Graph, str]:
    """Estación nueva (en su propia organización) y su API key en claro."""
    graph = await create_graph(conn)
    key = generate_api_key(graph.station_id)
    await conn.execute(
        "UPDATE core.stations SET api_key_hash = $1 WHERE id = $2",
        FAST_HASHER.hash(key),
        graph.station_id,
    )
    return graph, key


async def link_station(conn: asyncpg.Connection, graph: Graph, position: str = "in_zone") -> None:
    """Asigna la estación del grafo a su zona (sin esto, ninguna regla le aplica)."""
    await conn.execute(
        "INSERT INTO core.zone_stations (zone_id, station_id, position) VALUES ($1, $2, $3)",
        graph.zone_id,
        graph.station_id,
        position,
    )


async def create_rule(
    conn: asyncpg.Connection,
    graph: Graph,
    rule_type: str,
    params: dict[str, object],
    *,
    station_id: UUID | None = None,
    severity: str = "warning",
) -> UUID:
    rule_id = uuid7()
    await conn.execute(
        """
        INSERT INTO core.rules (id, organization_id, zone_id, station_id, type, params,
                                severity, escalation_policy_id, cooldown_s)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, 600)
        """,
        rule_id,
        graph.organization_id,
        graph.zone_id,
        station_id,
        rule_type,
        json.dumps(params),
        severity,
        graph.policy_id,
    )
    return rule_id
