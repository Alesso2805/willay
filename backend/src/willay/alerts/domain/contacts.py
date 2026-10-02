"""Contacts (VIG-36): the people Willay alerts, by email and/or Telegram, with or without an
account. A contact may have no channel yet; the dashboard flags it, since nobody can reach it.
"""

import re
from dataclasses import dataclass

MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 254  # RFC 5321
# Deliberately loose: it catches a slip such as "rosa@rimac"; whether an address really
# exists is for the mail server to say, and a failed delivery is recorded (alert_failed).
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class ContactData:
    full_name: str
    email: str | None


class InvalidContactError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def validate_contact(data: ContactData) -> None:
    if not data.full_name or len(data.full_name) > MAX_NAME_LENGTH:
        raise InvalidContactError(
            "full_name", f"El nombre debe tener entre 1 y {MAX_NAME_LENGTH} caracteres."
        )
    if data.email is not None and (
        len(data.email) > MAX_EMAIL_LENGTH or not _EMAIL.fullmatch(data.email)
    ):
        raise InvalidContactError("email", "El correo no es válido.")
