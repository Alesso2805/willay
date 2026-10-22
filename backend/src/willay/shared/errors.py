"""What went wrong, as stable codes.

A code never changes, so clients may rely on it; the text is its translation in the request's
language (shared/i18n.py, `errors.<code>` in locales/*.json). Errors carry codes and their
parameters, never text in one language: translating is the API's job.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    TOKEN_INVALID = "token_invalid"
    ORGANIZATION_REQUIRED = "organization_required"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    PERMISSION_DENIED = "permission_denied"
    AUDIT_DATE_ORDER = "audit_date_order"
    AUDIT_CURSOR_INVALID = "audit_cursor_invalid"
    API_KEY_INVALID = "api_key_invalid"
    STATION_INACTIVE = "station_inactive"
    RATE_LIMITED = "rate_limited"
    KEY_FAILURES_LIMITED = "key_failures_limited"
    READING_IN_FUTURE = "reading_in_future"
    ZONE_NOT_FOUND = "zone_not_found"
    STATION_NOT_FOUND = "station_not_found"
    STATION_CODE_TAKEN = "station_code_taken"
    RULE_NOT_FOUND = "rule_not_found"
    INCIDENT_NOT_FOUND = "incident_not_found"
    INCIDENT_TRANSITION = "incident_transition"
    CONTACT_NOT_FOUND = "contact_not_found"
    CONTACT_HAS_HISTORY = "contact_has_history"
    TELEGRAM_NOT_CONFIGURED = "telegram_not_configured"
    GROUP_NOT_FOUND = "group_not_found"
    GROUP_NAME_TAKEN = "group_name_taken"
    GROUP_IN_USE = "group_in_use"
    POLICY_NOT_FOUND = "policy_not_found"
    POLICY_IN_USE = "policy_in_use"
    POLICY_NAME_TAKEN = "policy_name_taken"
    # validation, by the domain
    CONTACT_NAME_LENGTH = "contact_name_length"
    CONTACT_EMAIL_INVALID = "contact_email_invalid"
    GROUP_NAME_LENGTH = "group_name_length"
    GROUP_ZONE_UNKNOWN = "group_zone_unknown"
    GROUP_MEMBER_UNKNOWN = "group_member_unknown"
    POLICY_NAME_LENGTH = "policy_name_length"
    POLICY_LEVEL_COUNT = "policy_level_count"
    POLICY_LEVEL_WAIT = "policy_level_wait"
    POLICY_LEVEL_NO_TARGET = "policy_level_no_target"
    POLICY_LEVEL_REPEATED_TARGET = "policy_level_repeated_target"
    POLICY_GROUPS_UNKNOWN = "policy_groups_unknown"
    RULE_STATION_REQUIRED = "rule_station_required"
    RULE_COOLDOWN_RANGE = "rule_cooldown_range"
    RULE_PARAMS_INVALID = "rule_params_invalid"
    RULE_TYPE_FIXED = "rule_type_fixed"
    RULE_ZONE_UNKNOWN = "rule_zone_unknown"
    RULE_STATION_OUTSIDE_ZONE = "rule_station_outside_zone"
    RULE_POLICY_UNKNOWN = "rule_policy_unknown"
    STATION_LOCATION_RANGE = "station_location_range"
    STATION_CODE_FORMAT = "station_code_format"
    STATION_TOO_MANY_ZONES = "station_too_many_zones"
    STATION_ZONE_REPEATED = "station_zone_repeated"
    STATION_ZONES_UNKNOWN = "station_zones_unknown"
    GEOMETRY_TYPE = "geometry_type"
    GEOMETRY_EMPTY = "geometry_empty"
    GEOMETRY_TOO_MANY_VERTICES = "geometry_too_many_vertices"
    GEOMETRY_NO_RING = "geometry_no_ring"
    GEOMETRY_RING_TYPE = "geometry_ring_type"
    GEOMETRY_RING_TOO_SHORT = "geometry_ring_too_short"
    GEOMETRY_RING_OPEN = "geometry_ring_open"
    GEOMETRY_POSITION = "geometry_position"
    GEOMETRY_NOT_NUMBERS = "geometry_not_numbers"
    GEOMETRY_OUT_OF_RANGE = "geometry_out_of_range"
    GEOMETRY_INVALID = "geometry_invalid"
    ORGANIZATION_TIMEZONE_UNKNOWN = "organization_timezone_unknown"
    DEMO_UNAVAILABLE = "demo_unavailable"
    DEMO_RUN_ACTIVE = "demo_run_active"


class CodedError(Exception):
    """An error that names its problem with a code and its parameters: the API translates it."""

    def __init__(self, code: ErrorCode, **params: object) -> None:
        super().__init__(code.value)
        self.code = code
        self.params = params


class FieldError(CodedError):
    """A code about one input field: answered as a 422 in FastAPI's shape."""

    def __init__(self, field: str, code: ErrorCode, **params: object) -> None:
        super().__init__(code, **params)
        self.field = field


class Term(str):
    """A parameter that is itself a translation key, translated in the same language as the
    message: `Term("incident_status.resolved")` reads "resuelto" or "resolved"."""

    __slots__ = ()


class Names(tuple[str, ...]):
    """Names quoted the way the message's language quotes them: «Protocolo Rímac» in
    Spanish, “Protocolo Rímac” in English."""

    __slots__ = ()
