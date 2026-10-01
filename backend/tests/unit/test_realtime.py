import json
from uuid import uuid4

from vigia.realtime.application.broadcaster import Broadcaster
from vigia.realtime.domain.events import RESYNC, RealtimeEvent, parse_notification

ORG_A, ORG_B = uuid4(), uuid4()


def test_a_notification_becomes_an_event_without_its_organization() -> None:
    payload = json.dumps(
        {"organization_id": str(ORG_A), "type": "incident", "incident_id": "i1", "event": "opened"}
    )
    event = parse_notification(payload)
    assert event == RealtimeEvent(ORG_A, "incident", {"incident_id": "i1", "event": "opened"})


def test_unreadable_or_unknown_notifications_are_dropped() -> None:
    assert parse_notification("no es json") is None
    assert parse_notification(json.dumps({"type": "incident"})) is None  # sin organización
    assert parse_notification(json.dumps({"organization_id": "x", "type": "incident"})) is None
    unknown = json.dumps({"organization_id": str(ORG_A), "type": "otro"})
    assert parse_notification(unknown) is None
    assert parse_notification(json.dumps(["lista"])) is None


async def test_events_only_reach_their_own_organization() -> None:
    broadcaster = Broadcaster()
    with broadcaster.subscribe(ORG_A) as a, broadcaster.subscribe(ORG_B) as b:
        broadcaster.publish(RealtimeEvent(ORG_A, "station", {"station_id": "s1"}))
        assert (await a.next()).data == {"station_id": "s1"}
        assert b.pending == 0
    assert broadcaster.connections == 0  # al cerrar, la suscripción se va


async def test_a_slow_client_gets_a_resync_instead_of_a_growing_queue() -> None:
    broadcaster = Broadcaster(queue_size=2)
    with broadcaster.subscribe(ORG_A) as slow:
        for n in range(3):
            broadcaster.publish(RealtimeEvent(ORG_A, "station", {"n": n}))
        assert (await slow.next()).type == RESYNC
        assert slow.pending == 0


async def test_losing_the_database_connection_resyncs_everyone() -> None:
    broadcaster = Broadcaster()
    with broadcaster.subscribe(ORG_A) as a, broadcaster.subscribe(ORG_B) as b:
        broadcaster.resync_all()
        assert (await a.next()).type == (await b.next()).type == RESYNC
