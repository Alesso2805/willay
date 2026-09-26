"""Permisos del rol vigia_app (criterios de aceptación de VIG-03)."""

import asyncpg
import pytest
from uuid_utils.compat import uuid7

from tests.integration.factories import T0, create_graph, create_incident, create_organization

pytestmark = pytest.mark.integration

APPEND_ONLY = ["core.incident_events", "core.audit_log"]


@pytest.mark.parametrize("table", APPEND_ONLY)
async def test_app_cannot_update_or_delete_append_only_tables(
    app: asyncpg.Connection, table: str
) -> None:
    # El chequeo de privilegios ocurre antes de mirar filas: WHERE false basta.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute(f"UPDATE {table} SET organization_id = organization_id WHERE false")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute(f"DELETE FROM {table} WHERE false")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute(f"TRUNCATE {table}")


async def test_app_can_append_to_incident_timeline_but_not_rewrite_it(
    owner: asyncpg.Connection, app: asyncpg.Connection
) -> None:
    graph = await create_graph(owner)
    incident_id = await create_incident(owner, graph)

    event_id = await app.fetchval(
        """
        INSERT INTO core.incident_events (incident_id, organization_id, occurred_at,
                                          event_type, actor_type, payload)
        VALUES ($1, $2, $3, 'opened', 'system', '{"readings": []}')
        RETURNING id
        """,
        incident_id,
        graph.organization_id,
        T0,
    )
    assert await app.fetchval("SELECT count(*) FROM core.incident_events WHERE id = $1", event_id)

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute(
            "UPDATE core.incident_events SET event_type = 'comment' WHERE id = $1", event_id
        )


async def test_app_can_append_to_audit_log_but_not_rewrite_it(
    owner: asyncpg.Connection, app: asyncpg.Connection
) -> None:
    org_id = await create_organization(owner)
    await app.execute(
        """
        INSERT INTO core.audit_log (organization_id, entity_type, entity_id, action, after, at)
        VALUES ($1, 'station', $2, 'create', '{}', $3)
        """,
        org_id,
        uuid7(),
        T0,
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute("DELETE FROM core.audit_log WHERE organization_id = $1", org_id)


@pytest.mark.parametrize("schema", ["core", "ingest"])
async def test_table_created_later_by_owner_is_granted_to_app(
    owner: asyncpg.Connection, app: asyncpg.Connection, schema: str
) -> None:
    # Lo mismo que hará cualquier migración futura: vigia_owner crea una tabla.
    table = f"{schema}.future_{uuid7().hex[:8]}"
    await owner.execute(f"CREATE TABLE {table} (id bigint GENERATED ALWAYS AS IDENTITY, v int)")
    try:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert await app.fetchval("SELECT has_table_privilege($1, $2)", table, privilege)
        # La identity necesita USAGE sobre su secuencia, también otorgado por defecto.
        await app.execute(f"INSERT INTO {table} (v) VALUES (1)")
        await app.execute(f"UPDATE {table} SET v = 2")
        await app.execute(f"DELETE FROM {table}")
    finally:
        await owner.execute(f"DROP TABLE {table}")


async def test_app_cannot_change_the_schema(app: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute("CREATE TABLE core.intruder (id int)")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute("DROP TABLE core.rules")
