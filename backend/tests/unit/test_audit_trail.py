"""VIG-38: audit log pages and their cursor."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from willay.identity.application.audit_trail import (
    AuditFilters,
    AuditRecord,
    Author,
    read_page,
)
from willay.identity.domain.audit_trail import (
    Cursor,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)

T0 = datetime(2026, 12, 22, 9, 0, 0, 123456, tzinfo=UTC)
ORG = uuid4()


def test_a_cursor_comes_back_exactly_as_it_went() -> None:
    cursor = Cursor(T0, 42)
    token = encode_cursor(cursor)
    assert "=" not in token  # safe in a URL as is
    assert decode_cursor(token) == cursor


@pytest.mark.parametrize("token", ["", "basura", encode_cursor(Cursor(T0, 1))[:-3], "MjAyNnwx"])
def test_an_unreadable_cursor_is_refused(token: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(token)


class FakeTrail:
    def __init__(self, count: int) -> None:
        self.records = [
            AuditRecord(
                i,
                T0 - timedelta(minutes=i),
                None,
                None,
                "rule",
                uuid4(),
                None,
                "update",
                None,
                None,
            )
            for i in range(1, count + 1)
        ]
        self.asked: list[tuple[Cursor | None, int]] = []

    async def page(
        self, organization_id: UUID, filters: AuditFilters, after: Cursor | None, limit: int
    ) -> list[AuditRecord]:
        self.asked.append((after, limit))
        older = [r for r in self.records if after is None or (r.at, r.id) < (after.at, after.id)]
        return older[:limit]

    async def authors(self, organization_id: UUID) -> list[Author]:
        return []


async def test_pages_follow_each_other_until_the_last_one() -> None:
    trail = FakeTrail(5)
    first = await read_page(ORG, AuditFilters(), None, 2, trail=trail)
    assert [r.id for r in first.records] == [1, 2]
    assert first.next_cursor is not None
    second = await read_page(ORG, AuditFilters(), decode_cursor(first.next_cursor), 2, trail=trail)
    assert [r.id for r in second.records] == [3, 4]
    assert second.next_cursor is not None
    last = await read_page(ORG, AuditFilters(), decode_cursor(second.next_cursor), 2, trail=trail)
    assert [r.id for r in last.records] == [5]
    assert last.next_cursor is None
    assert {limit for _, limit in trail.asked} == {3}  # one more, to know if there is a next page


async def test_an_exact_last_page_says_there_is_nothing_after_it() -> None:
    page = await read_page(ORG, AuditFilters(), None, 5, trail=FakeTrail(5))
    assert (len(page.records), page.next_cursor) == (5, None)
