"""What went wrong, as stable codes (VIG-40).

A code never changes, so clients may rely on it; the text is its translation in the request's
language (shared/i18n.py, `errors.<code>` in locales/*.json). Errors carry codes and their
parameters, never text in one language: translating is the API's job.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    # identity
    TOKEN_INVALID = "token_invalid"
    ORGANIZATION_REQUIRED = "organization_required"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    PERMISSION_DENIED = "permission_denied"
    AUDIT_DATE_ORDER = "audit_date_order"
    AUDIT_CURSOR_INVALID = "audit_cursor_invalid"
    # ingestion
    API_KEY_INVALID = "api_key_invalid"
    STATION_INACTIVE = "station_inactive"
    RATE_LIMITED = "rate_limited"
    READING_IN_FUTURE = "reading_in_future"
    # territory
    ZONE_NOT_FOUND = "zone_not_found"
    STATION_NOT_FOUND = "station_not_found"
    STATION_CODE_TAKEN = "station_code_taken"
    # rules
    RULE_NOT_FOUND = "rule_not_found"
    # incidents
    INCIDENT_NOT_FOUND = "incident_not_found"
    INCIDENT_TRANSITION = "incident_transition"
    # alerts
    CONTACT_NOT_FOUND = "contact_not_found"
    CONTACT_HAS_HISTORY = "contact_has_history"
    TELEGRAM_NOT_CONFIGURED = "telegram_not_configured"
    GROUP_NOT_FOUND = "group_not_found"
    GROUP_NAME_TAKEN = "group_name_taken"
    GROUP_IN_USE = "group_in_use"
    POLICY_NOT_FOUND = "policy_not_found"
    POLICY_IN_USE = "policy_in_use"
    POLICY_NAME_TAKEN = "policy_name_taken"


class Term(str):
    """A parameter that is itself a translation key, translated in the same language as the
    message: `Term("incident_status.resolved")` reads "resuelto" or "resolved"."""

    __slots__ = ()


class Names(tuple[str, ...]):
    """Names quoted the way the message's language quotes them: «Protocolo Rímac» in
    Spanish, “Protocolo Rímac” in English."""

    __slots__ = ()
