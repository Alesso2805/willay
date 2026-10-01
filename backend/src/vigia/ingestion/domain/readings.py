"""Station readings: batch rules independent of HTTP and SQL."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

MAX_BATCH_SIZE = 500
# Tolerated station clock skew. Beyond it, a reading "from the future" means a misconfigured
# clock: accepting it would open rule windows with impossible data.
MAX_CLOCK_SKEW = timedelta(minutes=5)
# A reading arriving more than 1 h after measurement is useless for timely alerts: it is
# stored for history but neither evaluated nor counted as a heartbeat (SPEC).
LATE_AFTER = timedelta(hours=1)


class Quality(StrEnum):
    OK = "ok"
    LATE = "late"


@dataclass(frozen=True)
class Reading:
    measured_at: datetime
    value: float


@dataclass(frozen=True)
class ClassifiedReading:
    measured_at: datetime
    value: float
    quality: Quality


class FutureReadingsError(Exception):
    def __init__(self, indices: list[int]) -> None:
        super().__init__(f"readings with measured_at in the future: {indices}")
        self.indices = indices


def check_not_in_future(readings: Sequence[Reading], now: datetime) -> None:
    limit = now + MAX_CLOCK_SKEW
    late = [i for i, reading in enumerate(readings) if reading.measured_at > limit]
    if late:
        raise FutureReadingsError(late)


def quality_of(measured_at: datetime, received_at: datetime) -> Quality:
    return Quality.LATE if received_at - measured_at > LATE_AFTER else Quality.OK


def heartbeat_reading(readings: Sequence[ClassifiedReading]) -> ClassifiedReading | None:
    """The reading that updates the heartbeat: the most recently measured non-late one.

    None if the batch has only late readings: data from hours ago does not prove the station is
    alive now, so silence detection must still see it as silent. Duplicates do count:
    resending recent readings shows the station is communicating.
    """
    on_time = [r for r in readings if r.quality is Quality.OK]
    return max(on_time, key=lambda r: r.measured_at) if on_time else None


def classify(readings: Sequence[Reading], received_at: datetime) -> list[ClassifiedReading]:
    """Sort by measured_at (stations may send unordered batches) and set each reading's
    quality from how long it took to arrive."""
    ordered = sorted(readings, key=lambda reading: reading.measured_at)
    return [
        ClassifiedReading(r.measured_at, r.value, quality_of(r.measured_at, received_at))
        for r in ordered
    ]
