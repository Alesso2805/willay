"""Carga idempotente de los datos semilla.

Cada fila tiene un id fijo y se inserta con ON CONFLICT (id) DO NOTHING: reejecutar
el seed no duplica ni modifica nada. Las API keys solo se generan para estaciones
recién creadas o, con rotate_keys, para todas las del seed.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.ingestion.infrastructure.api_keys import ApiKeyHasher, generate_api_key
from vigia.seed import data
from vigia.shared.clock import Clock


@dataclass(frozen=True)
class IssuedKey:
    organization_alias: str
    station_id: UUID
    station_code: str
    api_key: str


async def load_seed(
    conn: AsyncConnection, clock: Clock, hasher: ApiKeyHasher, *, rotate_keys: bool = False
) -> list[IssuedKey]:
    await _insert_territory(conn)
    issued = await _insert_stations(conn, clock, hasher, rotate_keys=rotate_keys)
    await _insert_contacts(conn)
    await _insert_policies(conn)
    await _insert_rules(conn)
    return issued


async def _insert_territory(conn: AsyncConnection) -> None:
    for org in data.ORGANIZATIONS:
        await conn.execute(
            text("""
                INSERT INTO core.organizations (id, keycloak_org_id, name, timezone)
                VALUES (:id, :keycloak_org_id, :name, :timezone)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": org.id,
                "keycloak_org_id": org.keycloak_org_id,
                "name": org.name,
                "timezone": org.timezone,
            },
        )
    for zone in data.ZONES:
        await conn.execute(
            text("""
                INSERT INTO core.risk_zones (id, organization_id, name, description, risk_level,
                                             geom, population_estimate)
                VALUES (:id, :organization_id, :name, :description, :risk_level,
                        ST_GeomFromText(:wkt, 4326), :population_estimate)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": zone.id,
                "organization_id": zone.organization_id,
                "name": zone.name,
                "description": zone.description,
                "risk_level": zone.risk_level,
                "wkt": zone.wkt,
                "population_estimate": zone.population_estimate,
            },
        )


async def _insert_stations(
    conn: AsyncConnection, clock: Clock, hasher: ApiKeyHasher, *, rotate_keys: bool
) -> list[IssuedKey]:
    aliases = {org.id: org.alias for org in data.ORGANIZATIONS}
    issued: list[IssuedKey] = []
    for station in data.STATIONS:
        api_key = generate_api_key(station.id)
        params = {
            "id": station.id,
            "api_key_hash": hasher.hash(api_key),
            "rotated_at": clock.now(),
        }
        created = await conn.scalar(
            text("""
                INSERT INTO core.stations (id, organization_id, code, name, variable, unit,
                                           location, source, expected_interval_s,
                                           silence_multiplier, api_key_hash, api_key_rotated_at)
                VALUES (:id, :organization_id, :code, :name, :variable, :unit,
                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :source,
                        :expected_interval_s, :silence_multiplier, :api_key_hash, :rotated_at)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """),
            {
                **params,
                "organization_id": station.organization_id,
                "code": station.code,
                "name": station.name,
                "variable": station.variable,
                "unit": station.unit,
                "lon": station.lon,
                "lat": station.lat,
                "source": station.source,
                "expected_interval_s": station.expected_interval_s,
                "silence_multiplier": station.silence_multiplier,
            },
        )
        if created is None and rotate_keys:
            await conn.execute(
                text("""
                    UPDATE core.stations
                    SET api_key_hash = :api_key_hash, api_key_rotated_at = :rotated_at
                    WHERE id = :id
                """),
                params,
            )
        if created is not None or rotate_keys:
            issued.append(
                IssuedKey(aliases[station.organization_id], station.id, station.code, api_key)
            )

        for zone_id, position in station.zones:
            await conn.execute(
                text("""
                    INSERT INTO core.zone_stations (zone_id, station_id, position)
                    VALUES (:zone_id, :station_id, :position)
                    ON CONFLICT (zone_id, station_id) DO NOTHING
                """),
                {"zone_id": zone_id, "station_id": station.id, "position": position},
            )
    return issued


async def _insert_contacts(conn: AsyncConnection) -> None:
    for contact in data.CONTACTS:
        await conn.execute(
            text("""
                INSERT INTO core.contacts (id, organization_id, full_name, email)
                VALUES (:id, :organization_id, :full_name, :email)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": contact.id,
                "organization_id": contact.organization_id,
                "full_name": contact.full_name,
                "email": contact.email,
            },
        )
    for group in data.CONTACT_GROUPS:
        await conn.execute(
            text("""
                INSERT INTO core.contact_groups (id, organization_id, name, zone_id)
                VALUES (:id, :organization_id, :name, :zone_id)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": group.id,
                "organization_id": group.organization_id,
                "name": group.name,
                "zone_id": group.zone_id,
            },
        )
        for contact_id in group.members:
            await conn.execute(
                text("""
                    INSERT INTO core.contact_group_members (group_id, contact_id)
                    VALUES (:group_id, :contact_id)
                    ON CONFLICT DO NOTHING
                """),
                {"group_id": group.id, "contact_id": contact_id},
            )


async def _insert_policies(conn: AsyncConnection) -> None:
    for policy in data.POLICIES:
        await conn.execute(
            text("""
                INSERT INTO core.escalation_policies (id, organization_id, name)
                VALUES (:id, :organization_id, :name)
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": policy.id, "organization_id": policy.organization_id, "name": policy.name},
        )
        for level in policy.levels:
            await conn.execute(
                text("""
                    INSERT INTO core.escalation_levels (id, policy_id, level_order, wait_s)
                    VALUES (:id, :policy_id, :level_order, :wait_s)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": level.id,
                    "policy_id": policy.id,
                    "level_order": level.level_order,
                    "wait_s": level.wait_s,
                },
            )
            for target_id, group_id, channel in level.targets:
                await conn.execute(
                    text("""
                        INSERT INTO core.level_targets (id, level_id, contact_group_id, channel)
                        VALUES (:id, :level_id, :group_id, :channel)
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {"id": target_id, "level_id": level.id, "group_id": group_id,
                     "channel": channel},
                )  # fmt: skip


async def _insert_rules(conn: AsyncConnection) -> None:
    for rule in data.RULES:
        await conn.execute(
            text("""
                INSERT INTO core.rules (id, organization_id, zone_id, station_id, type, params,
                                        severity, escalation_policy_id, cooldown_s)
                VALUES (:id, :organization_id, :zone_id, :station_id, :type,
                        CAST(:params AS jsonb), :severity, :escalation_policy_id, :cooldown_s)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": rule.id,
                "organization_id": rule.organization_id,
                "zone_id": rule.zone_id,
                "station_id": rule.station_id,
                "type": rule.type,
                "params": rule.params_json,
                "severity": rule.severity,
                "escalation_policy_id": rule.escalation_policy_id,
                "cooldown_s": rule.cooldown_s,
            },
        )
