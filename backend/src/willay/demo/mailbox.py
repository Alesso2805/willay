"""Level 2 acknowledges by email when nobody there has Telegram linked.

The demo acts as one level-2 contact: it reads their alert emails in Mailpit and presses the
confirmation page's button, the same POST a person makes. So whoever clones the repository
without a Telegram bot still sees the whole story, level 2 included.
"""

import re
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import httpx2

from willay.demo.story import ACK_LEVEL
from willay.shared.clock import Clock

# A person takes a moment to read the email; meanwhile the narration shows the level-2 alerts.
READING_DELAY_S = 10.0
_TOKEN = re.compile(r"/confirmar/([A-Za-z0-9_-]{20,})")

# (incident_id, level_order) of the alert a token belongs to, or None (e.g. a previous run's).
AlertLookup = Callable[[str], Awaitable[tuple[UUID, int] | None]]
# Presses the confirmation page's button for a token; returns the HTTP status.
Confirm = Callable[[str], Awaitable[int]]


def confirm_token(text: str) -> str | None:
    """The acknowledgement token in an alert email's link."""
    match = _TOKEN.search(text)
    return match.group(1) if match else None


class Mailbox(Protocol):
    async def messages_to(self, address: str) -> list[str]:
        """Ids of the latest messages sent to the address."""
        ...

    async def text(self, message_id: str) -> str: ...


class MailpitMailbox:
    """Mailpit's API (https://mailpit.axllent.org/docs/api-v1/), over the compose network."""

    def __init__(self, client: httpx2.AsyncClient) -> None:
        self._client = client

    async def messages_to(self, address: str) -> list[str]:
        response = await self._client.get(
            "/api/v1/search", params={"query": f'to:"{address}"', "limit": 50}
        )
        response.raise_for_status()
        return [message["ID"] for message in response.json().get("messages") or []]

    async def text(self, message_id: str) -> str:
        response = await self._client.get(f"/api/v1/message/{message_id}")
        response.raise_for_status()
        return str(response.json().get("Text", ""))


@dataclass(frozen=True)
class Recipient:
    name: str
    email: str


class EmailAcknowledger:
    """Presses the button of the recipient's level-2 alert emails for the story's incidents,
    once each, a few seconds after the email arrives."""

    def __init__(
        self,
        recipient: Recipient,
        mailbox: Mailbox,
        lookup: AlertLookup,
        confirm: Confirm,
        clock: Clock,
        *,
        delay_s: float = READING_DELAY_S,
    ) -> None:
        self.recipient = recipient
        self._mailbox = mailbox
        self._lookup = lookup
        self._confirm = confirm
        self._clock = clock
        self._delay_s = delay_s
        self._waiting: dict[str, tuple[UUID, str, datetime]] = {}  # message -> incident, token
        self._done: set[str] = set()

    async def step(self, incidents: Collection[UUID]) -> list[tuple[UUID, str]]:
        """What it acknowledged in this step, as (incident_id, narration)."""
        now = self._clock.now()
        for message_id in await self._mailbox.messages_to(self.recipient.email):
            if message_id in self._done or message_id in self._waiting:
                continue
            token = confirm_token(await self._mailbox.text(message_id))
            alert = await self._lookup(token) if token is not None else None
            if token is None or alert is None or alert[0] not in incidents or alert[1] != ACK_LEVEL:
                self._done.add(message_id)  # not a level-2 alert of this run: never acted on
                continue
            self._waiting[message_id] = (alert[0], token, now)
        acknowledged = []
        for message_id, (incident_id, token, seen_at) in list(self._waiting.items()):
            if (now - seen_at).total_seconds() < self._delay_s:
                continue
            del self._waiting[message_id]
            self._done.add(message_id)
            status = await self._confirm(token)
            outcome = "" if status == 200 else f" (the page answered {status})"
            acknowledged.append(
                (incident_id, f"the demo presses Confirm in {self.recipient.name}'s email{outcome}")
            )
        return acknowledged
