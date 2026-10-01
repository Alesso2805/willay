"""Silent sensor rule (VIG-17): a station that stopped reporting.

A station is silent once K * expected_interval_s have passed since its last heartbeat
(`station_heartbeats.last_seen_at`). K comes only from `stations.silence_multiplier` (SPEC),
so a station has the same threshold in every rule watching it. A station that never reported
is not silent: otherwise a freshly seeded stack would open incidents before receiving data.
"""

from datetime import datetime, timedelta


def silence_threshold(expected_interval_s: int, multiplier: int) -> timedelta:
    return timedelta(seconds=expected_interval_s * multiplier)


def is_silent(last_seen_at: datetime | None, threshold: timedelta, now: datetime) -> bool:
    return last_seen_at is not None and now - last_seen_at >= threshold
