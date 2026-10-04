"""Rules as the operator manages them (VIG-27): what a rule watches, how bad it is and whom it
alerts. Whether it fires is decided by threshold.py, rate_of_change.py and silence.py; this
module checks that a rule is one the evaluator will understand.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from willay.incidents.domain.severity import Severity
from willay.rules.domain.errors import InvalidRuleParamsError
from willay.rules.domain.rate_of_change import parse_rate_of_change
from willay.rules.domain.threshold import parse_threshold
from willay.shared.errors import ErrorCode, FieldError

# A day: staying quiet longer after an incident is resolved is ignoring the zone.
MAX_COOLDOWN_S = 86_400


class RuleType(StrEnum):
    THRESHOLD = "threshold"
    RATE_OF_CHANGE = "rate_of_change"
    SILENCE = "silence"


# A value is compared in its station's unit (SPEC: a rule never compares different units),
# so these types name their station. Only silence makes sense for a whole zone.
NEEDS_STATION = frozenset({RuleType.THRESHOLD, RuleType.RATE_OF_CHANGE})


@dataclass(frozen=True)
class RuleData:
    zone_id: UUID
    station_id: UUID | None  # None: every station of the zone (silence only)
    params: Mapping[str, Any]
    severity: Severity
    escalation_policy_id: UUID
    cooldown_s: int
    is_active: bool


class InvalidRuleError(FieldError, ValueError):
    pass


def checked(rule_type: RuleType, data: RuleData) -> RuleData:
    """The same rule with its params in canonical form, or InvalidRuleError."""
    if rule_type in NEEDS_STATION and data.station_id is None:
        raise InvalidRuleError("station_id", ErrorCode.RULE_STATION_REQUIRED)
    if not 0 <= data.cooldown_s <= MAX_COOLDOWN_S:
        raise InvalidRuleError("cooldown_s", ErrorCode.RULE_COOLDOWN_RANGE, max=MAX_COOLDOWN_S)
    return RuleData(
        zone_id=data.zone_id,
        station_id=data.station_id,
        params=canonical_params(rule_type, data.params),
        severity=data.severity,
        escalation_policy_id=data.escalation_policy_id,
        cooldown_s=data.cooldown_s,
        is_active=data.is_active,
    )


def canonical_params(rule_type: RuleType, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Parsed by the same functions the evaluator uses, so what is stored is what it reads."""
    try:
        match rule_type:
            case RuleType.THRESHOLD:
                threshold = parse_threshold(raw)
                return {
                    "operator": threshold.operator.value,
                    "value": threshold.value,
                    "consecutive": threshold.consecutive,
                }
            case RuleType.RATE_OF_CHANGE:
                rate = parse_rate_of_change(raw)
                return {
                    "direction": rate.direction.value,
                    "delta": rate.delta,
                    "window_minutes": rate.window_minutes,
                }
            case RuleType.SILENCE:
                if raw:  # K lives in stations.silence_multiplier (SPEC): nothing to set here
                    raise InvalidRuleParamsError(f"silence takes no params: {dict(raw)}")
                return {}
    except InvalidRuleParamsError as exc:
        raise InvalidRuleError("params", ErrorCode.RULE_PARAMS_INVALID) from exc
