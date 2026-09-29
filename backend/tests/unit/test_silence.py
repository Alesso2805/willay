from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from vigia.incidents.application.open_incident import Trigger
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
        "station_id": uuid4(),
        "expected_interval_s": 10,
        "silence_multiplier": 3,
        "last_seen_at": last_seen_at,
        "last_measured_at": T0 - timedelta(seconds=2),
        "last_value": 84.2,
    }
    return WatchedStation(**(defaults | kw))


class Repository:
    def __init__(self, *stations: WatchedStation) -> None:
        self.stations = list(stations)

    async def watched(self, tx: Any) -> list[WatchedStation]:
        return self.stations


class Incidents:
    def __init__(self, *, already_open: bool = False) -> None:
        self.opened: list[Trigger] = []
        self.already_open = already_open

    async def open(self, tx: Any, trigger: Trigger, now: datetime) -> UUID | None:
        self.opened.append(trigger)
        return None if self.already_open else uuid4()


@asynccontextmanager
async def _transaction() -> AsyncIterator[AsyncConnection]:
    yield cast(AsyncConnection, object())


def _checker(repository: Repository, incidents: Incidents, clock: FakeClock) -> SilenceChecker:
    return SilenceChecker(repository, incidents, clock, _transaction)


async def test_only_silent_stations_open_an_incident() -> None:
    silent = _station(T0)
    almost = _station(T0 + timedelta(seconds=1))  # le falta 1 s
    never = _station(None)
    incidents = Incidents()

    cycle = await _checker(
        Repository(silent, almost, never), incidents, FakeClock(T0 + THIRTY_S)
    ).run()

    assert cycle == SilenceCycle(watched=3, silent=1, opened=1)
    assert [t.station_id for t in incidents.opened] == [silent.station_id]


async def test_advancing_the_clock_turns_a_station_silent() -> None:
    clock, incidents = FakeClock(T0 + timedelta(seconds=20)), Incidents()
    checker = _checker(Repository(_station(T0)), incidents, clock)

    assert (await checker.run()).opened == 0
    clock.advance(timedelta(seconds=10))
    assert (await checker.run()).opened == 1


async def test_the_trigger_names_the_station_and_keeps_its_last_reading() -> None:
    station, incidents = _station(T0), Incidents()
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
    station, incidents = replace(_station(T0), last_value=None), Incidents()
    await _checker(Repository(station), incidents, FakeClock(T0 + THIRTY_S)).run()

    [trigger] = incidents.opened
    assert (trigger.trigger_value, trigger.evidence) == (None, ())


async def test_an_incident_already_open_is_not_counted_again() -> None:
    incidents = Incidents(already_open=True)
    cycle = await _checker(Repository(_station(T0)), incidents, FakeClock(T0 + THIRTY_S)).run()
    assert cycle == SilenceCycle(watched=1, silent=1, opened=0)
