"""LISTEN/NOTIFY channel names (ADR-0002), shared by producers and consumers.

A NOTIFY inside a transaction is delivered only if it commits, so consumers never wake for
rolled-back rows. NOTIFY is not durable (lost if nobody listens), so workers also poll every 5 s.
"""

# API and demo worker -> evaluator: new rows in ingest.evaluation_queue. No payload: the
# evaluator claims rows with SKIP LOCKED and does not need to know which ones.
EVALUATION_QUEUE = "willay_evaluation_queue"

# Evaluator and workers -> dispatcher: pending rows in core.alerts. No payload for the same
# reason: the dispatcher claims them with SKIP LOCKED.
ALERTS = "willay_alerts"

# Database -> API: every incident event and station heartbeat (VIG-25), and every reading that
# fails evaluation or is reprocessed (VIG-39). Emitted by triggers (migrations 0008 and 0009,
# ADR-0007) with a JSON payload: organization_id for routing plus the minimum
# the dashboard needs to know what to refresh. The API relays it over SSE.
EVENTS = "willay_events"
