"""The load test's own organization ("Carga") and a clean slate for each run (VIG-29).

Idempotent: the first run creates the organization, its zone, contact, policy, stations and
rules; later runs only issue new API keys (they live in memory for the run, never on disk)
and resolve the incidents a previous run left open, so every spike can open its incident
again. Singletons have fixed uuid7 ids, as in the seed; stations are found by their code and
rules by their station.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from uuid_utils.compat import uuid7

from willay.ingestion.domain.api_keys import generate_api_key
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher
from willay.loadtest.plan import THRESHOLD_M

ORGANIZATION = UUID("01a0ffb7-8dfe-7f72-bb93-76166fc14c4e")
KEYCLOAK_ORGANIZATION = UUID("01a0ffb7-8dfe-7f72-bb93-762002a39890")  # no one logs in to it
ZONE = UUID("01a0ffb7-8dfe-7f72-bb93-76338bbcc035")
CONTACT = UUID("01a0ffb7-8dfe-7f72-bb93-7643ee582204")
GROUP = UUID("01a0ffb7-8dfe-7f72-bb93-76575fed2af4")
POLICY = UUID("01a0ffb7-8dfe-7f72-bb93-76607755d47b")
LEVEL = UUID("01a0ffb7-8dfe-7f72-bb93-767beb4e7f25")
TARGET = UUID("01a0ffb7-8dfe-7f72-bb93-76835a4840f2")
LEVEL_WAIT_S = 3600  # nobody acknowledges during the run: it must not escalate meanwhile

_SINGLETONS = [
    """INSERT INTO core.organizations (id, keycloak_org_id, name, timezone)
       VALUES (:organization, :keycloak, 'Carga (prueba de carga)', 'America/Lima')
       ON CONFLICT (id) DO NOTHING""",
    """INSERT INTO core.risk_zones (id, organization_id, name, risk_level, geom)
       VALUES (:zone, :organization, 'Zona de carga', 'low', ST_GeomFromText(
           'MULTIPOLYGON(((-75.6 -12.4, -75.4 -12.4, -75.4 -12.6, -75.6 -12.6, -75.6 -12.4)))',
           4326))
       ON CONFLICT (id) DO NOTHING""",
    """INSERT INTO core.contacts (id, organization_id, full_name, email)
       VALUES (:contact, :organization, 'Equipo de carga', 'carga@loadtest.willay.test')
       ON CONFLICT (id) DO NOTHING""",
    """INSERT INTO core.contact_groups (id, organization_id, name)
       VALUES (:group, :organization, 'Equipo de carga') ON CONFLICT (id) DO NOTHING""",
    """INSERT INTO core.contact_group_members (group_id, contact_id)
       VALUES (:group, :contact) ON CONFLICT DO NOTHING""",
    """INSERT INTO core.escalation_policies (id, organization_id, name)
       VALUES (:policy, :organization, 'Protocolo de carga') ON CONFLICT (id) DO NOTHING""",
    """INSERT INTO core.escalation_levels (id, policy_id, level_order, wait_s)
       VALUES (:level, :policy, 1, :wait_s) ON CONFLICT (id) DO NOTHING""",
    """INSERT INTO core.level_targets (id, level_id, contact_group_id, channel)
       VALUES (:target, :level, :group, 'email') ON CONFLICT (id) DO NOTHING""",
]

_STATION = text("""
    INSERT INTO core.stations (id, organization_id, code, name, variable, unit, location,
                               source, expected_interval_s, silence_multiplier,
                               api_key_hash, api_key_rotated_at)
    VALUES (:id, :organization, :code, :name, 'water_level', 'm',
            ST_SetSRID(ST_MakePoint(-75.5, -12.5), 4326), 'simulator', 10, 3,
            :api_key_hash, :now)
    ON CONFLICT (organization_id, code) DO UPDATE
        SET api_key_hash = EXCLUDED.api_key_hash,
            api_key_rotated_at = EXCLUDED.api_key_rotated_at, status = 'active'
    RETURNING id
""")

# Cooldown 0: a cause resolved by the previous run's clean-up may open again right away.
_RULE = text("""
    INSERT INTO core.rules (id, organization_id, zone_id, station_id, type, params, severity,
                            escalation_policy_id, cooldown_s)
    SELECT :id, :organization, :zone, :station_id, 'threshold', CAST(:params AS jsonb),
           'warning', :policy, 0
    WHERE NOT EXISTS (SELECT 1 FROM core.rules
                      WHERE station_id = :station_id AND type = 'threshold')
""")

# Incidents a previous run left open would swallow this run's spikes (one active per cause).
_RESET = text("""
    UPDATE core.incidents
    SET status = 'resolved', resolved_at = :now, resolution = 'false_alarm'
    WHERE organization_id = :organization AND status IN ('open', 'acknowledged')
""")


@dataclass(frozen=True)
class LoadStation:
    id: UUID
    code: str
    api_key: str


async def prepare(
    conn: AsyncConnection, stations: int, now: datetime, hasher: ApiKeyHasher
) -> list[LoadStation]:
    ids = {
        "organization": ORGANIZATION, "keycloak": KEYCLOAK_ORGANIZATION, "zone": ZONE,
        "contact": CONTACT, "group": GROUP, "policy": POLICY, "level": LEVEL, "target": TARGET,
        "wait_s": LEVEL_WAIT_S,
    }  # fmt: skip
    for statement in _SINGLETONS:
        await conn.execute(text(statement), ids)
    prepared = [await _station(conn, number, now, hasher) for number in range(1, stations + 1)]
    await conn.execute(_RESET, {"organization": ORGANIZATION, "now": now})
    return prepared


async def _station(
    conn: AsyncConnection, number: int, now: datetime, hasher: ApiKeyHasher
) -> LoadStation:
    code = f"CAR-{number:03d}"
    new_id = uuid7()
    # The key embeds its station's id: issued after knowing whether the station existed.
    station_id: UUID = await conn.scalar(
        _STATION,
        {
            "id": new_id,
            "organization": ORGANIZATION,
            "code": code,
            "name": f"Estación de carga {number}",
            "api_key_hash": "pending",
            "now": now,
        },
    )
    api_key = generate_api_key(station_id)
    await conn.execute(
        text("UPDATE core.stations SET api_key_hash = :hash WHERE id = :id"),
        {"id": station_id, "hash": hasher.hash(api_key)},
    )
    await conn.execute(
        text("""
            INSERT INTO core.zone_stations (zone_id, station_id, position)
            VALUES (:zone, :station_id, 'in_zone') ON CONFLICT DO NOTHING
        """),
        {"zone": ZONE, "station_id": station_id},
    )
    await conn.execute(
        _RULE,
        {
            "id": uuid7(),
            "organization": ORGANIZATION,
            "zone": ZONE,
            "station_id": station_id,
            "params": f'{{"operator": "gt", "value": {THRESHOLD_M}, "consecutive": 1}}',
            "policy": POLICY,
        },
    )
    return LoadStation(station_id, code, api_key)
