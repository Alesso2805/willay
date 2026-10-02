"""The workers' LISTEN keeps itself connected: retries a failed start and reopens a dropped
connection, waking the worker once to catch up. Driven with a fake connection."""

import asyncio
from collections.abc import Callable
from typing import Any

from willay.shared.pg_listen import listen

FAST = {"retry_first_s": 0.01, "retry_max_s": 0.02}


class FakeConnection:
    def __init__(self) -> None:
        self.listeners: dict[str, Callable[..., None]] = {}
        self.on_lost: Callable[..., None] | None = None
        self.closed = False
        self.listening = asyncio.Event()

    async def add_listener(self, channel: str, callback: Callable[..., None]) -> None:
        self.listeners[channel] = callback

    def add_termination_listener(self, callback: Callable[..., None]) -> None:
        self.on_lost = callback
        self.listening.set()

    async def close(self) -> None:
        self.closed = True

    def notify(self, channel: str) -> None:
        self.listeners[channel](self, 1, channel, "")

    def drop(self) -> None:
        assert self.on_lost is not None
        self.on_lost(self)


async def test_a_notification_wakes_the_worker() -> None:
    conn = FakeConnection()

    async def connect(_: str) -> Any:
        return conn

    async with listen("dsn", "willay_alerts", connect=connect, **FAST) as wakeup:
        async with asyncio.timeout(1):
            await conn.listening.wait()
        assert not wakeup.is_set()  # the first connection needs no catch-up: the worker starts
        conn.notify("willay_alerts")
        assert wakeup.is_set()
    assert conn.closed


async def test_it_keeps_trying_while_the_database_is_starting_and_then_catches_up() -> None:
    conn = FakeConnection()
    attempts = 0

    async def connect(_: str) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("the database system is starting up")
        return conn

    async with listen("dsn", "willay_alerts", connect=connect, **FAST) as wakeup:
        async with asyncio.timeout(1):
            await wakeup.wait()  # set once it got through, to catch up with what it missed
        assert attempts == 3
        wakeup.clear()
        conn.notify("willay_alerts")
        assert wakeup.is_set()


async def test_a_dropped_connection_is_reopened_and_the_worker_catches_up() -> None:
    first, second = FakeConnection(), FakeConnection()
    connections = [first, second]

    async def connect(_: str) -> Any:
        return connections.pop(0)

    async with listen("dsn", "willay_alerts", connect=connect, **FAST) as wakeup:
        async with asyncio.timeout(1):
            await first.listening.wait()
        first.drop()  # the database restarted
        async with asyncio.timeout(1):
            await wakeup.wait()
        assert first.closed
        wakeup.clear()
        second.notify("willay_alerts")
        assert wakeup.is_set()


async def test_an_unexpected_error_does_not_stop_it_for_good() -> None:
    conn = FakeConnection()
    attempts = 0

    async def connect(_: str) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("something nobody expected")
        return conn

    async with listen("dsn", "willay_alerts", connect=connect, **FAST) as wakeup:
        async with asyncio.timeout(1):
            await wakeup.wait()
        assert attempts == 2
