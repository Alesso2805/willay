"""Rule preview use case (VIG-27): a draft rule replayed over the last 24 h of its station's
`ok` readings, or of every station of the zone for a zone-wide silence rule. Nothing is
written: it only answers "when would this rule have opened an incident?".
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from willay.rules.domain.preview import (
    Firing,
    Point,
    rate_of_change_firings,
    silence_firings,
    threshold_firings,
)
from willay.rules.domain.rate_of_change import MAX_WINDOW_MINUTES, parse_rate_of_change
from willay.rules.domain.rules import InvalidRuleError, RuleType, canonical_params
from willay.rules.domain.silence import silence_threshold
from willay.rules.domain.threshold import parse_threshold
from willay.shared.clock import Clock
from willay.shared.errors import ErrorCode

PERIOD = timedelta(hours=24)
# Readings before the period that rules may still look at: the longest rate-of-change window.
# A threshold run longer than an hour that started before the period is not seen whole.
WARMUP = timedelta(minutes=MAX_WINDOW_MINUTES)
MAX_POINTS = 20_000  # 24 h at one reading every 5 s is 17 280


@dataclass(frozen=True)
class PreviewStation:
    id: UUID
    code: str
    name: str
    unit: str
    expected_interval_s: int
    silence_multiplier: int


@dataclass(frozen=True)
class StationPreview:
    station: PreviewStation
    readings: list[Point]  # within the period, oldest first, for the chart
    firings: list[Firing]
    truncated: bool  # more readings than MAX_POINTS: the oldest were left out


@dataclass(frozen=True)
class Preview:
    since: datetime
    until: datetime
    stations: list[StationPreview]


class PreviewRepository(Protocol):
    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool: ...

    async def stations(
        self, organization_id: UUID, zone_id: UUID, station_id: UUID | None
    ) -> list[PreviewStation]:
        """The station if it is in the zone, or the zone's active stations if None."""
        ...

    async def readings(
        self, station_id: UUID, since: datetime, until: datetime, limit: int
    ) -> list[Point]:
        """`ok` readings, oldest first; the latest `limit` if there are more."""
        ...

    async def last_reported_before(self, station_id: UUID, moment: datetime) -> datetime | None:
        """When it last reported (`received_at` of an `ok` reading) before `moment`."""
        ...

    async def reported(self, station_id: UUID, since: datetime, until: datetime) -> list[datetime]:
        """Distinct `received_at` of its `ok` readings in the period, oldest first."""
        ...


async def preview_rule(
    organization_id: UUID,
    rule_type: RuleType,
    zone_id: UUID,
    station_id: UUID | None,
    raw_params: Mapping[str, Any],
    *,
    repository: PreviewRepository,
    clock: Clock,
) -> Preview:
    params = canonical_params(rule_type, raw_params)
    if rule_type is not RuleType.SILENCE and station_id is None:
        raise InvalidRuleError("station_id", ErrorCode.RULE_STATION_REQUIRED)
    if not await repository.zone_exists(organization_id, zone_id):
        raise InvalidRuleError("zone_id", ErrorCode.RULE_ZONE_UNKNOWN)
    stations = await repository.stations(organization_id, zone_id, station_id)
    if station_id is not None and not stations:
        raise InvalidRuleError("station_id", ErrorCode.RULE_STATION_OUTSIDE_ZONE)

    until = clock.now()
    since = until - PERIOD
    previews = []
    for station in stations:
        readings = await repository.readings(station.id, since - WARMUP, until, MAX_POINTS + 1)
        truncated = len(readings) > MAX_POINTS
        readings = readings[-MAX_POINTS:]
        firings = await _firings(rule_type, params, station, readings, since, until, repository)
        shown = [r for r in readings if r.at >= since]
        previews.append(StationPreview(station, shown, firings, truncated))
    return Preview(since, until, previews)


async def _firings(
    rule_type: RuleType,
    params: Mapping[str, Any],
    station: PreviewStation,
    readings: list[Point],
    since: datetime,
    until: datetime,
    repository: PreviewRepository,
) -> list[Firing]:
    match rule_type:
        # Up to a few seconds of CPU on a dense day: in a thread, so the API keeps serving.
        case RuleType.THRESHOLD:
            return await asyncio.to_thread(
                threshold_firings, parse_threshold(params), readings, since
            )
        case RuleType.RATE_OF_CHANGE:
            return await asyncio.to_thread(
                rate_of_change_firings, parse_rate_of_change(params), readings, since
            )
        case RuleType.SILENCE:
            # Silence goes by when the station reported, as the heartbeat does, not by measured_at.
            threshold = silence_threshold(station.expected_interval_s, station.silence_multiplier)
            before = await repository.last_reported_before(station.id, since)
            received = await repository.reported(station.id, since, until)
            return silence_firings(
                threshold, [*([before] if before else []), *received], since, until
            )
