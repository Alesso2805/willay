from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from tests.support.alerts import FakeAlerting
from tests.support.incidents import FakeIncidentStore
from vigia.incidents.application.station_recovery import Recovery
from vigia.incidents.domain.incidents import EvidenceReading
from vigia.rules.application.silence_check import SilenceChecker, SilenceCycle, WatchedStation
from vigia.rules.domain.silence import is_silent, silence_threshold
from vigia.shared.clock import FakeClock

T0 = datetime(2026, 11, 9, 8, 50, tzinfo=UTC)  # último latido
THIRTY_S = timedelta(seconds=30)  # K = 3 * intervalo de 10 s


def test_the_threshold_is_k_times_the_expected_interval() -> None:
    assert silence_threshold(10, 3) == THIRTY_S
    assert silence_threshold(600, 2) == timedelta(minutes=20)


def test_a_station_is_silent_from_exactly_k_times_the_interval() -> None:
    assert is_silent(T0, THIRTY_S, T0 + THIRTY_S)
    assert not is_silent(T0, THIRTY_S, T0 + THIRTY_S - timedelta(microseconds=1))


def test_a_station_that_never_reported_is_not_silent() -> None:
    assert not is_silent(None, THIRTY_S, T0 + timedelta(days=1))


def _station(last_seen_at: datetime | None = T0, **kw: Any) -> WatchedStation:
    defaults: dict[str, Any] = {
        "rule_id": uuid4(),
        "organization_id": uuid4(),
        "zone_id": uuid4(),
        "rule_params": {},
        "severity": "critical",
        "cooldown_s": 600,
        "station_id": uuid4(),
        "expected_interval_s": 10,
        "silence_multiplier": 3,
        "last_seen_at": last_seen_at,
        "last_measured_at": T0 - timedelta(seconds=2),
        "last_value": 84.2,
    }
    return WatchedStation(**(defaults | kw))


class Repository:
    def __init__(self, *stations: WatchedStation, recoveries: tuple[Recovery, ...] = ()) -> None:
        self.stations = list(stations)
        self.pending_recoveries = list(recoveries)

    async def watched(self, tx: Any) -> list[WatchedStation]:
        return self.stations

    async def recoveries(self, tx: Any) -> list[Recovery]:
        return self.pending_recoveries


@asynccontextmanager
async def _transaction() -> AsyncIterator[AsyncConnection]:
    yield cast(AsyncConnection, object())


def _checker(
    repository: Repository, incidents: FakeIncidentStore, clock: FakeClock
) -> SilenceChecker:
    return SilenceChecker(repository, incidents, clock, _transaction, alerts=FakeAlerting())


async def test_only_silent_stations_open_an_incident() -> None:
    silent = _station(T0)
    almost = _station(T0 + timedelta(seconds=1))  # le falta 1 s
    never = _station(None)
    incidents = FakeIncidentStore()

    cycle = await _checker(
        Repository(silent, almost, never), incidents, FakeClock(T0 + THIRTY_S)
    ).run()

    assert cycle == SilenceCycle(watched=3, silent=1, opened=1, recovered=0)
    assert [t.station_id for t in incidents.opened] == [silent.station_id]


async def test_advancing_the_clock_turns_a_station_silent() -> None:
    clock, incidents = FakeClock(T0 + timedelta(seconds=20)), FakeIncidentStore()
    checker = _checker(Repository(_station(T0)), incidents, clock)

    assert (await checker.run()).opened == 0
    clock.advance(timedelta(seconds=10))
    assert (await checker.run()).opened == 1


async def test_the_trigger_names_the_station_and_keeps_its_last_reading() -> None:
    station, incidents = _station(T0), FakeIncidentStore()
    await _checker(Repository(station), incidents, FakeClock(T0 + THIRTY_S)).run()

    [trigger] = incidents.opened
    assert trigger.rule_type == "silence"
    # Con la estación en la causa: dos estaciones calladas son dos incidentes.
    assert trigger.dedup_key == f"{station.rule_id}:{station.zone_id}:{station.station_id}"
    assert trigger.trigger_value == 84.2
    assert trigger.evidence == (EvidenceReading(T0 - timedelta(seconds=2), 84.2),)
    assert trigger.details == {
        "last_seen_at": T0.isoformat(),
        "expected_interval_s": 10,
        "silence_multiplier": 3,
    }


async def test_a_station_without_a_last_value_opens_without_evidence() -> None:
    station, incidents = replace(_station(T0), last_value=None), FakeIncidentStore()
    await _checker(Repository(station), incidents, FakeClock(T0 + THIRTY_S)).run()

    [trigger] = incidents.opened
    assert (trigger.trigger_value, trigger.evidence) == (None, ())


async def test_an_incident_already_open_is_not_counted_again() -> None:
    checker = _checker(Repository(_station(T0)), FakeIncidentStore(), FakeClock(T0 + THIRTY_S))
    await checker.run()
    assert await checker.run() == SilenceCycle(watched=1, silent=1, opened=0, recovered=0)


async def test_a_silent_station_does_not_reopen_while_its_cause_cools_down() -> None:
    incidents = FakeIncidentStore(cooling_down=True)
    cycle = await _checker(Repository(_station(T0)), incidents, FakeClock(T0 + THIRTY_S)).run()
    assert (cycle.opened, incidents.opened) == (0, [])


def _recovery() -> Recovery:
    return Recovery(uuid4(), uuid4(), uuid4(), T0 + timedelta(minutes=5), None, 85.0)


async def test_a_station_that_reports_again_is_recorded_as_recovered() -> None:
    recovery, incidents = _recovery(), FakeIncidentStore()
    clock = FakeClock(T0 + timedelta(minutes=6))
    cycle = await _checker(Repository(recoveries=(recovery,)), incidents, clock).run()

    assert cycle.recovered == 1
    assert incidents.recovered == [(recovery, clock.now())]
    assert incidents.opened == []  # la recuperación no abre ni cierra nada


async def test_a_recovery_recorded_by_another_worker_is_not_counted() -> None:
    incidents = FakeIncidentStore(recovered_before=True)
    cycle = await _checker(
        Repository(recoveries=(_recovery(),)), incidents, FakeClock(T0 + timedelta(minutes=6))
    ).run()
    assert cycle.recovered == 0
