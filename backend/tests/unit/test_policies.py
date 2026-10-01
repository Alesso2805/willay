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
    ("policy", "message"),
    [
        (_policy(name="   "), "el nombre"),
        (_policy(name="x" * 121), "el nombre"),
        (PolicyData("Vacía", ()), "entre 1 y 10 niveles"),
        (_policy(*(LevelData(60, (EMAIL,)),) * 11), "entre 1 y 10 niveles"),
        (_policy(LevelData(0, (EMAIL,))), "nivel 1: la espera"),
        (_policy(LevelData(120, (EMAIL,)), LevelData(86_401, (EMAIL,))), "nivel 2: la espera"),
        (_policy(LevelData(120, ())), "nivel 1: necesita al menos un grupo"),
        (_policy(LevelData(120, (EMAIL, EMAIL))), "nivel 1: el mismo grupo y canal"),
    ],
)
def test_invalid_policies_are_rejected_with_a_reason(policy: PolicyData, message: str) -> None:
    with pytest.raises(InvalidPolicyError, match=message):
        validate_policy(policy)
