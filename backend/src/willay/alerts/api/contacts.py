"""Contacts API (VIG-21, VIG-36): the people Willay alerts.

Admin and operator read (SPEC: contact data is for them); only admin writes, audited. A
contact's Telegram chat never leaves the API: only whether it is linked, and until when a
link sent to them still works. The link itself is shown once: only its token hash is stored,
so it cannot be read again; if lost, a new one is generated and the old one stops working.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, field_validator

from willay.alerts.application.contacts import (
    Contact,
    ContactHasHistoryError,
    create_contact,
    delete_contact,
    remove_from_all_groups,
    unlink_telegram,
    update_contact,
)
from willay.alerts.application.policies import Actor
from willay.alerts.application.telegram_link import (
    ContactNotFoundError,
    TelegramNotConfiguredError,
    create_telegram_link,
)
from willay.alerts.domain.contacts import ContactData, InvalidContactError
from willay.alerts.infrastructure.contacts_repository import SqlContactRepository
from willay.alerts.infrastructure.sql_contact_links import SqlContactLinkRepository
from willay.identity.api.dependencies import require
from willay.identity.domain.permissions import Permission
from willay.identity.domain.principal import Principal
from willay.shared.audit import SqlAuditLog
from willay.shared.clock import Clock
from willay.shared.errors import ErrorCode
from willay.shared.web import ApiError, ClockDep, DbConnection, SettingsDep, invalid_field

router = APIRouter(prefix="/v1/contacts", tags=["alerts"])

CanView = Annotated[Principal, Depends(require(Permission.VIEW_CONTACT_DETAILS))]
CanManage = Annotated[Principal, Depends(require(Permission.MANAGE_CONTACTS))]

_NOT_FOUND = ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.CONTACT_NOT_FOUND)
_RESPONSES: dict[int | str, dict[str, str]] = {404: {"description": "Not found"}}


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str
    email: str | None = None

    @field_validator("email")
    @classmethod
    def _blank_is_none(cls, email: str | None) -> str | None:
        return email or None  # an emptied field means "no email"

    @property
    def data(self) -> ContactData:
        return ContactData(self.full_name, self.email)


class GroupRefOut(BaseModel):
    id: UUID
    name: str


class ContactOut(BaseModel):
    id: UUID
    full_name: str
    email: str | None
    telegram_linked: bool
    telegram_link_expires_at: datetime | None
    groups: list[GroupRefOut]
    has_history: bool


class TelegramLinkOut(BaseModel):
    url: str
    expires_at: datetime


@router.get("", summary="The organization's contacts, by name")
async def list_contacts(
    principal: CanView, conn: DbConnection, clock: ClockDep
) -> list[ContactOut]:
    contacts = await SqlContactRepository(conn).all_of(principal.organization_id)
    return [_out(contact, clock) for contact in contacts]


@router.get("/{contact_id}", summary="A contact", responses=_RESPONSES)
async def get_contact(
    contact_id: UUID, principal: CanView, conn: DbConnection, clock: ClockDep
) -> ContactOut:
    contact = await SqlContactRepository(conn).get(principal.organization_id, contact_id)
    if contact is None:
        raise _NOT_FOUND
    return _out(contact, clock)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a contact")
async def post_contact(
    body: ContactIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> ContactOut:
    try:
        contact = await create_contact(
            _actor(principal), body.data, contacts=SqlContactRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except InvalidContactError as exc:
        raise _invalid(exc) from exc
    return _out(contact, clock)


@router.put("/{contact_id}", summary="Edit a contact's name and email", responses=_RESPONSES)
async def put_contact(
    contact_id: UUID, body: ContactIn, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> ContactOut:
    try:
        contact = await update_contact(
            _actor(principal), contact_id, body.data, contacts=SqlContactRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except ContactNotFoundError as exc:
        raise _NOT_FOUND from exc
    except InvalidContactError as exc:
        raise _invalid(exc) from exc
    return _out(contact, clock)


@router.delete(
    "/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a contact without history",
    responses={
        **_RESPONSES,
        409: {"description": "It has alerts or acknowledgements: remove it from its groups"},
    },
)
async def remove_contact(
    contact_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> Response:
    try:
        await delete_contact(
            _actor(principal), contact_id, contacts=SqlContactRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except ContactNotFoundError as exc:
        raise _NOT_FOUND from exc
    except ContactHasHistoryError as exc:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.CONTACT_HAS_HISTORY, name=exc.contact.full_name
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{contact_id}/remove-from-groups",
    summary="Remove a contact from all its groups, so it stops receiving alerts",
    responses=_RESPONSES,
)
async def post_remove_from_groups(
    contact_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> ContactOut:
    try:
        contact = await remove_from_all_groups(
            _actor(principal), contact_id, contacts=SqlContactRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except ContactNotFoundError as exc:
        raise _NOT_FOUND from exc
    return _out(contact, clock)


@router.delete(
    "/{contact_id}/telegram",
    summary="Unlink the contact's Telegram (and void any pending link)",
    responses=_RESPONSES,
)
async def delete_telegram(
    contact_id: UUID, principal: CanManage, conn: DbConnection, clock: ClockDep
) -> ContactOut:
    try:
        contact = await unlink_telegram(
            _actor(principal), contact_id, contacts=SqlContactRepository(conn),
            audit=SqlAuditLog(conn), clock=clock,
        )  # fmt: skip
    except ContactNotFoundError as exc:
        raise _NOT_FOUND from exc
    return _out(contact, clock)


@router.post(
    "/{contact_id}/telegram-link",
    status_code=status.HTTP_201_CREATED,
    summary="Single-use link for the contact to link their Telegram (shown once)",
    responses={
        404: {"description": "The contact does not exist"},
        503: {"description": "The Telegram bot is not configured"},
    },
)
async def post_telegram_link(
    contact_id: UUID,
    principal: CanManage,
    conn: DbConnection,
    clock: ClockDep,
    settings: SettingsDep,
    response: Response,
) -> TelegramLinkOut:
    try:
        link = await create_telegram_link(
            _actor(principal),
            contact_id,
            contacts=SqlContactLinkRepository(conn),
            audit=SqlAuditLog(conn),
            clock=clock,
            bot_username=settings.telegram_bot_username,
        )
    except ContactNotFoundError as exc:
        raise _NOT_FOUND from exc
    except TelegramNotConfiguredError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.TELEGRAM_NOT_CONFIGURED
        ) from exc
    response.headers["Cache-Control"] = "no-store"  # the link is a single-use secret
    return TelegramLinkOut(url=link.url, expires_at=link.expires_at)


def _actor(principal: Principal) -> Actor:
    return Actor(principal.organization_id, principal.user_id)


def _invalid(exc: InvalidContactError) -> ApiError:
    return invalid_field(exc)


def _out(contact: Contact, clock: Clock) -> ContactOut:
    return ContactOut(
        id=contact.id,
        full_name=contact.full_name,
        email=contact.email,
        telegram_linked=contact.telegram_linked,
        telegram_link_expires_at=contact.pending_link_until(clock.now()),
        groups=[GroupRefOut(id=g.id, name=g.name) for g in contact.groups],
        has_history=contact.has_history,
    )
