from uuid import uuid4

import pytest

from willay.alerts.domain.alerts import Channel
from willay.alerts.domain.policies import (
    InvalidPolicyError,
    LevelData,
    PolicyData,
    Target,
    validate_policy,
)
from willay.shared.errors import ErrorCode

GROUP = uuid4()
EMAIL = Target(GROUP, Channel.EMAIL)


def _policy(*levels: LevelData, name: str = "Protocolo") -> PolicyData:
    return PolicyData(name, levels or (LevelData(120, (EMAIL,)),))


def test_a_sensible_policy_is_valid() -> None:
    policy = _policy(
        LevelData(120, (EMAIL,)),
        LevelData(180, (EMAIL, Target(GROUP, Channel.TELEGRAM))),  # same group, another channel
    )
    validate_policy(policy)
    assert policy.group_ids == {GROUP}


@pytest.mark.parametrize(
    ("policy", "code", "params"),
    [
        (_policy(name="   "), ErrorCode.POLICY_NAME_LENGTH, {"max": 120}),
        (_policy(name="x" * 121), ErrorCode.POLICY_NAME_LENGTH, {"max": 120}),
        (PolicyData("Vacía", ()), ErrorCode.POLICY_LEVEL_COUNT, {"max": 10}),
        (_policy(*(LevelData(60, (EMAIL,)),) * 11), ErrorCode.POLICY_LEVEL_COUNT, {"max": 10}),
        (_policy(LevelData(0, (EMAIL,))), ErrorCode.POLICY_LEVEL_WAIT, {"level": 1, "max": 86_400}),
        (
            _policy(LevelData(120, (EMAIL,)), LevelData(86_401, (EMAIL,))),
            ErrorCode.POLICY_LEVEL_WAIT,
            {"level": 2, "max": 86_400},
        ),
        (_policy(LevelData(120, ())), ErrorCode.POLICY_LEVEL_NO_TARGET, {"level": 1}),
        (
            _policy(LevelData(120, (EMAIL, EMAIL))),
            ErrorCode.POLICY_LEVEL_REPEATED_TARGET,
            {"level": 1},
        ),
    ],
)
def test_invalid_policies_are_rejected_with_a_reason(
    policy: PolicyData, code: ErrorCode, params: dict[str, object]
) -> None:
    with pytest.raises(InvalidPolicyError) as caught:
        validate_policy(policy)
    assert (caught.value.code, caught.value.params) == (code, params)
