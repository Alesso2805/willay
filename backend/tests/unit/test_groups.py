"""VIG-36: contact group validation and use cases, with an in-memory repository."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from willay.alerts.application.groups import (
    ContactGroup,
    GroupInUseError,
    GroupNotFoundError,
    Ref,
    create_group,
    delete_group,
    update_group,
)
from willay.alerts.application.policies import Actor
from willay.alerts.domain.groups import GroupData, InvalidGroupError, validate_group
from willay.shared.audit import AuditEntry
from willay.shared.clock import FakeClock

T0 = datetime(2026, 12, 21, 10, 0, tzinfo=UTC)
ACTOR = Actor(uuid4(), uuid4())
ROSA = Ref(uuid4(), "Rosa Brigada")
LUCHO = Ref(uuid4(), "Lucho Quispe")
CHOSICA = Ref(uuid4(), "Chosica")


class FakeGroups:
    def __init__(self, *groups: ContactGroup) -> None:
        self.by_id = {g.id: g for g in groups}
        self.contacts = {c.id: c for c in (ROSA, LUCHO)}
        self.zones = {CHOSICA.id: CHOSICA}
        self.deleted: list[UUID] = []

    async def all_of(self, organization_id: UUID) -> list[ContactGroup]:
        return sorted(self.by_id.values(), key=lambda g: g.name)

    async def get(
        self, organization_id: UUID, group_id: UUID, *, for_update: bool = False
    ) -> ContactGroup | None:
        return self.by_id.get(group_id) if organization_id == ACTOR.organization_id else None

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool:
        return zone_id in self.zones

    async def missing_contacts(
        self, organization_id: UUID, contact_ids: frozenset[UUID]
    ) -> frozenset[UUID]:
        return contact_ids - self.contacts.keys()

    async def add(self, group_id: UUID, organization_id: UUID, data: GroupData) -> ContactGroup:
        self.by_id[group_id] = self._group(group_id, data, ())
        return self.by_id[group_id]

    async def replace(self, organization_id: UUID, group_id: UUID, data: GroupData) -> ContactGroup:
        self.by_id[group_id] = self._group(group_id, data, self.by_id[group_id].policies)
        return self.by_id[group_id]

    async def delete(self, organization_id: UUID, group_id: UUID) -> None:
        del self.by_id[group_id]
        self.deleted.append(group_id)

    def _group(self, group_id: UUID, data: GroupData, policies: tuple[Ref, ...]) -> ContactGroup:
        members = sorted((self.contacts[c] for c in data.member_ids), key=lambda c: c.name)
        zone = self.zones[data.zone_id] if data.zone_id is not None else None
        return ContactGroup(group_id, data.name, zone, tuple(members), policies)


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def _brigade(**changes: object) -> ContactGroup:
    base = ContactGroup(uuid4(), "Brigada Chosica", CHOSICA, (LUCHO, ROSA), ())
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["", "x" * 121])
def test_a_group_needs_a_name(name: str) -> None:
    with pytest.raises(InvalidGroupError) as caught:
        validate_group(GroupData(name, None, frozenset()))
    assert caught.value.field == "name"


async def test_creating_records_the_group_with_its_zone_and_members_by_name() -> None:
    groups, audit = FakeGroups(), FakeAudit()
    data = GroupData("Brigada Chosica", CHOSICA.id, frozenset({ROSA.id, LUCHO.id}))
    group = await create_group(ACTOR, data, groups=groups, audit=audit, clock=FakeClock(T0))
    assert [(e.action, e.entity_type, e.entity_id, e.before, e.after) for e in audit.entries] == [
        (
            "create",
            "contact_group",
            group.id,
            None,
            {
                "name": "Brigada Chosica",
                "zone": "Chosica",
                "members": ["Lucho Quispe", "Rosa Brigada"],
            },
        )
    ]


@pytest.mark.parametrize(
    ("data", "field"),
    [
        (GroupData("Brigada", uuid4(), frozenset()), "zone_id"),
        (GroupData("Brigada", None, frozenset({ROSA.id, uuid4()})), "member_ids"),
    ],
)
async def test_a_zone_or_contact_outside_the_organization_is_refused(
    data: GroupData, field: str
) -> None:
    groups, audit = FakeGroups(), FakeAudit()
    with pytest.raises(InvalidGroupError) as caught:
        await create_group(ACTOR, data, groups=groups, audit=audit, clock=FakeClock(T0))
    assert caught.value.field == field
    assert groups.by_id == {}
    assert audit.entries == []


async def test_an_edit_that_changes_nothing_writes_nothing() -> None:
    brigade = _brigade()
    groups, audit = FakeGroups(brigade), FakeAudit()
    same = await update_group(
        ACTOR, brigade.id, brigade.data, groups=groups, audit=audit, clock=FakeClock(T0)
    )
    assert same == brigade
    assert audit.entries == []


async def test_an_edit_records_before_and_after() -> None:
    brigade = _brigade()
    groups, audit = FakeGroups(brigade), FakeAudit()
    data = GroupData("Brigada Chosica", None, frozenset({ROSA.id}))
    updated = await update_group(
        ACTOR, brigade.id, data, groups=groups, audit=audit, clock=FakeClock(T0)
    )
    assert updated.members == (ROSA,)
    [entry] = audit.entries
    assert (entry.action, entry.before, entry.after) == (
        "update",
        {"name": "Brigada Chosica", "zone": "Chosica", "members": ["Lucho Quispe", "Rosa Brigada"]},
        {"name": "Brigada Chosica", "zone": None, "members": ["Rosa Brigada"]},
    )


async def test_a_group_a_policy_notifies_is_not_deleted() -> None:
    brigade = _brigade(policies=(Ref(uuid4(), "Protocolo Rímac"),))
    groups, audit = FakeGroups(brigade), FakeAudit()
    with pytest.raises(GroupInUseError) as caught:
        await delete_group(ACTOR, brigade.id, groups=groups, audit=audit, clock=FakeClock(T0))
    assert [p.name for p in caught.value.group.policies] == ["Protocolo Rímac"]
    assert groups.deleted == []
    assert audit.entries == []


async def test_deleting_an_unused_group_is_audited() -> None:
    brigade = _brigade()
    groups, audit = FakeGroups(brigade), FakeAudit()
    await delete_group(ACTOR, brigade.id, groups=groups, audit=audit, clock=FakeClock(T0))
    assert groups.deleted == [brigade.id]
    assert [(e.action, e.after) for e in audit.entries] == [("delete", None)]


async def test_another_organizations_group_does_not_exist() -> None:
    brigade = _brigade()
    groups, audit = FakeGroups(brigade), FakeAudit()
    stranger = Actor(uuid4(), uuid4())
    with pytest.raises(GroupNotFoundError):
        await update_group(
            stranger, brigade.id, brigade.data, groups=groups, audit=audit, clock=FakeClock(T0)
        )
    with pytest.raises(GroupNotFoundError):
        await delete_group(stranger, brigade.id, groups=groups, audit=audit, clock=FakeClock(T0))
