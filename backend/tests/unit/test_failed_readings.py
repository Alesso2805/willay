"""VIG-39: reprocessing failed readings is audited once per station."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from willay.rules.application.actor import Actor
from willay.rules.application.failed_readings import FailedReading, reprocess
from willay.shared.audit import AuditEntry
from willay.shared.clock import FakeClock

T0 = datetime(2026, 12, 22, 9, 0, tzinfo=UTC)
ACTOR = Actor(uuid4(), uuid4())
STATION_A, STATION_B = uuid4(), uuid4()


def _failed(queue_id: int, station_id: UUID, minute: int) -> FailedReading:
    return FailedReading(
        id=queue_id,
        station_id=station_id,
        station_code="RIM-X",
        station_name="X",
        measured_at=T0 - timedelta(minutes=minute),
        value=1.0,
        unit="m3/s",
        attempts=5,
        failed_at=T0,
        last_error=f"error {queue_id}",
    )


class FakeFailedReadings:
    def __init__(self, *failed: FailedReading) -> None:
        self.failed = {f.id: f for f in failed}
        self.requeued: list[int] = []

    async def all_of(self, organization_id: UUID, *, limit: int) -> list[FailedReading]:
        return list(self.failed.values())[:limit]

    async def count(self, organization_id: UUID) -> int:
        return len(self.failed)

    async def requeue(
        self, organization_id: UUID, ids: frozenset[int], now: datetime
    ) -> list[FailedReading]:
        picked = [self.failed.pop(i) for i in sorted(ids) if i in self.failed]
        self.requeued += [f.id for f in picked]
        return picked


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


async def test_one_audit_entry_per_station_lists_what_went_back_and_its_error() -> None:
    readings = FakeFailedReadings(
        _failed(1, STATION_A, 3), _failed(2, STATION_B, 2), _failed(3, STATION_A, 1)
    )
    audit = FakeAudit()
    requeued = await reprocess(
        ACTOR, frozenset({1, 2, 3}), readings=readings, audit=audit, clock=FakeClock(T0)
    )
    assert len(requeued) == 3
    by_station = {e.entity_id: e for e in audit.entries}
    assert set(by_station) == {STATION_A, STATION_B}
    entry = by_station[STATION_A]
    assert (entry.entity_type, entry.action, entry.actor_id, entry.before, entry.at) == (
        "station",
        "readings_reprocessed",
        ACTOR.user_id,
        None,
        T0,
    )
    assert entry.after == {
        "readings": [  # in measurement order
            {"measured_at": "2026-12-22T08:57:00+00:00", "attempts": 5, "last_error": "error 1"},
            {"measured_at": "2026-12-22T08:59:00+00:00", "attempts": 5, "last_error": "error 3"},
        ]
    }


async def test_nothing_requeued_records_nothing() -> None:
    readings, audit = FakeFailedReadings(), FakeAudit()
    requeued = await reprocess(
        ACTOR, frozenset({7}), readings=readings, audit=audit, clock=FakeClock(T0)
    )
    assert requeued == []
    assert audit.entries == []
