"""The demo organization back as the seed made it (VIG-43).

Visitors of the public demo change things: they rename zones, add rules, resolve incidents,
pick English. Every night the demo worker deletes everything the organization has and loads the
seed again, which recreates it row by row with its fixed ids. Its users stay (Keycloak owns
them), with their language forgotten, so the next visitor starts in their browser's.

It connects as willay_owner, like `make demo`'s clean slate (willay.demo.reset): incident events
and the audit log are append-only for willay_app. In one transaction: all or nothing.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.demo import reset
from willay.ingestion.infrastructure.api_keys import ApiKeyHasher
from willay.seed import data as seed
from willay.seed.loader import load_seed
from willay.shared.clock import Clock

_STATIONS = "SELECT id FROM core.stations WHERE organization_id = :organization_id"
_POLICIES = "SELECT id FROM core.escalation_policies WHERE organization_id = :organization_id"

# In foreign key order, after reset.clear removed incidents, alerts and readings.
_DELETE_CONFIGURATION = [
    f"DELETE FROM ingest.rate_limit_windows WHERE station_id IN ({_STATIONS})",
    "DELETE FROM core.rules WHERE organization_id = :organization_id",
    f"""DELETE FROM core.level_targets WHERE level_id IN (
            SELECT id FROM core.escalation_levels WHERE policy_id IN ({_POLICIES}))""",
    f"DELETE FROM core.escalation_levels WHERE policy_id IN ({_POLICIES})",
    "DELETE FROM core.escalation_policies WHERE organization_id = :organization_id",
    """DELETE FROM core.contact_group_members WHERE group_id IN (
            SELECT id FROM core.contact_groups WHERE organization_id = :organization_id)""",
    "DELETE FROM core.contact_groups WHERE organization_id = :organization_id",
    "DELETE FROM core.contacts WHERE organization_id = :organization_id",
    f"DELETE FROM core.zone_stations WHERE station_id IN ({_STATIONS})",
    "DELETE FROM core.stations WHERE organization_id = :organization_id",
    "DELETE FROM core.risk_zones WHERE organization_id = :organization_id",
    "DELETE FROM core.audit_log WHERE organization_id = :organization_id",
]
_RESET_ORGANIZATION = """
    UPDATE core.organizations SET name = :name, timezone = :timezone, language = 'es'
    WHERE id = :organization_id
"""
_FORGET_LANGUAGES = "UPDATE core.users SET language = NULL WHERE organization_id = :organization_id"


class NotASeedOrganizationError(Exception):
    """Only an organization the seed creates can be restored from it."""


async def restore(
    conn: AsyncConnection, organization_id: UUID, clock: Clock, hasher: ApiKeyHasher
) -> None:
    organization = next((o for o in seed.ORGANIZATIONS if o.id == organization_id), None)
    if organization is None:
        raise NotASeedOrganizationError(organization_id)
    params = {"organization_id": organization_id}
    await reset.clear(conn, organization_id)
    for statement in _DELETE_CONFIGURATION:
        await conn.execute(text(statement), params)
    await conn.execute(
        text(_RESET_ORGANIZATION),
        {**params, "name": organization.name, "timezone": organization.timezone},
    )
    await conn.execute(text(_FORGET_LANGUAGES), params)
    # New API keys for the recreated stations: nobody needs them, the demo worker feeds the
    # readings itself.
    await load_seed(conn, clock, hasher)
