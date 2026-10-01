"""Limit of 60 batches per minute per station (SPEC: Rate limit).

Fixed one-minute windows (hh:mm:00): the simplest and cheapest to count in Postgres. Known
trade-off: up to 120 batches fit in a few seconds around the minute boundary, which is
acceptable to protect the API from a runaway station.
"""

import math
from datetime import datetime, timedelta

MAX_BATCHES_PER_MINUTE = 60
WINDOW = timedelta(minutes=1)
# Only the current window is read; the silence worker purges windows older than this on
# every cycle so the table does not grow forever.
WINDOW_RETENTION = timedelta(hours=1)


class RateLimitExceededError(Exception):
    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"limit of {MAX_BATCHES_PER_MINUTE} batches per minute exceeded")
        self.retry_after_s = retry_after_s


def window_start(now: datetime) -> datetime:
    return now.replace(second=0, microsecond=0)


def seconds_until_next_window(now: datetime) -> int:
    remaining = (window_start(now) + WINDOW - now).total_seconds()
    return max(1, math.ceil(remaining))


def check_count(count: int, now: datetime) -> None:
    """`count` includes the current batch."""
    if count > MAX_BATCHES_PER_MINUTE:
        raise RateLimitExceededError(seconds_until_next_window(now))
