"""Real-time notice of failed readings: NOTIFY willay_events (VIG-39, ADR-0007).

Whenever a queue row gets `failed_at` (the evaluator gave up on it) or loses it (an operator
reprocessed it), the dashboard header refetches the count of failed readings. As in 0008, a
trigger means no code path can forget to notify, and the notice is delivered only on commit.

The payload carries only the organization and the type: Postgres delivers identical payloads
once per transaction, so reprocessing a hundred rows sends one notice, not a hundred.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION ingest.notify_failed_readings() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('willay_events', json_build_object(
                'organization_id', NEW.organization_id,
                'type', 'failed_readings'
            )::text);
            RETURN NULL;
        END
        $$
    """)
    # WHEN filters in the executor, before calling the function: the evaluator's frequent
    # claim updates (attempts, available_at) cost nothing extra.
    op.execute("""
        CREATE TRIGGER evaluation_queue_failed_notify
        AFTER UPDATE OF failed_at ON ingest.evaluation_queue
        FOR EACH ROW
        WHEN (OLD.failed_at IS DISTINCT FROM NEW.failed_at)
        EXECUTE FUNCTION ingest.notify_failed_readings()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER evaluation_queue_failed_notify ON ingest.evaluation_queue")
    op.execute("DROP FUNCTION ingest.notify_failed_readings()")
