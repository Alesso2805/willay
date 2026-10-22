"""An organization's own settings: the language of its contacts' alerts when they chose
none, and the time zone of every time Willay writes for it (emails, Telegram, the dashboard)."""

from dataclasses import dataclass
from functools import cache
from zoneinfo import available_timezones

from willay.shared.errors import ErrorCode, FieldError
from willay.shared.languages import Language


@dataclass(frozen=True)
class OrganizationSettings:
    language: Language
    timezone: str  # an IANA name, such as America/Lima


class InvalidOrganizationError(FieldError, ValueError):
    pass


@cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_settings(settings: OrganizationSettings) -> None:
    """Only an IANA name: an offset such as "-05:00" ignores daylight saving time."""
    if settings.timezone not in _timezones():
        raise InvalidOrganizationError(
            "timezone", ErrorCode.ORGANIZATION_TIMEZONE_UNKNOWN, timezone=settings.timezone
        )
