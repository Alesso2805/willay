import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.support.tokens import KC_RIMAC, SUB_RIMAC_OPERATOR, TokenFactory, org_claim
from vigia.identity.infrastructure.jwt_verifier import TokenInvalidError
from vigia.shared.clock import FakeClock

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def tokens(clock: FakeClock) -> TokenFactory:
    return TokenFactory(clock)


async def test_valid_token_returns_its_claims(tokens: TokenFactory) -> None:
    token = tokens.issue(SUB_RIMAC_OPERATOR, organization=org_claim(("rimac", KC_RIMAC)))
    claims = await tokens.verifier().verify(token)
    assert claims["sub"] == str(SUB_RIMAC_OPERATOR)
    assert claims["organization"] == {"rimac": {"id": str(KC_RIMAC)}}


async def test_expiry_is_checked_with_the_injected_clock(
    tokens: TokenFactory, clock: FakeClock
) -> None:
    token = tokens.issue(SUB_RIMAC_OPERATOR, lifetime=timedelta(minutes=5))
    verifier = tokens.verifier()
    clock.advance(timedelta(minutes=5, seconds=30))  # dentro del margen de 30 s
    await verifier.verify(token)
    clock.advance(timedelta(seconds=1))
    with pytest.raises(TokenInvalidError, match="expiró"):
        await verifier.verify(token)


async def test_token_not_yet_valid_is_rejected(tokens: TokenFactory) -> None:
    claims = tokens.claims(SUB_RIMAC_OPERATOR, nbf=int((NOW + timedelta(minutes=5)).timestamp()))
    with pytest.raises(TokenInvalidError, match="aún no"):
        await tokens.verifier().verify(tokens.sign(claims))


@pytest.mark.parametrize(
    "override",
    [
        {"aud": "otro-cliente"},
        {"iss": "http://keycloak.test/realms/otro"},
    ],
)
async def test_wrong_audience_or_issuer_is_rejected(
    tokens: TokenFactory, override: dict[str, Any]
) -> None:
    token = tokens.sign(tokens.claims(SUB_RIMAC_OPERATOR, **override))
    with pytest.raises(TokenInvalidError):
        await tokens.verifier().verify(token)


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "aud", "iss"])
async def test_required_claims_must_be_present(tokens: TokenFactory, missing: str) -> None:
    claims = tokens.claims(SUB_RIMAC_OPERATOR)
    del claims[missing]
    with pytest.raises(TokenInvalidError):
        await tokens.verifier().verify(tokens.sign(claims))


async def test_token_signed_by_another_key_is_rejected(tokens: TokenFactory) -> None:
    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = tokens.sign(tokens.claims(SUB_RIMAC_OPERATOR), key=impostor)
    with pytest.raises(TokenInvalidError):
        await tokens.verifier().verify(token)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _segments(alg: str, claims: dict[str, object]) -> str:
    header = _b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    return f"{header}.{_b64(json.dumps(claims).encode())}"


async def test_alg_none_is_rejected(tokens: TokenFactory) -> None:
    unsigned = _segments("none", tokens.claims(SUB_RIMAC_OPERATOR)) + "."
    with pytest.raises(TokenInvalidError):
        await tokens.verifier().verify(unsigned)


async def test_hs256_signed_with_the_public_key_is_rejected(tokens: TokenFactory) -> None:
    # Ataque clásico: la clave pública es conocida; el atacante la usa como secreto HMAC
    # esperando que el verificador acepte HS256. Se arma a mano porque PyJWT ni lo firma.
    public_pem = tokens.public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signing_input = _segments("HS256", tokens.claims(SUB_RIMAC_OPERATOR))
    signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    forged = f"{signing_input}.{_b64(signature)}"
    with pytest.raises(TokenInvalidError):
        await tokens.verifier().verify(forged)


async def test_garbage_is_rejected(tokens: TokenFactory) -> None:
    with pytest.raises(TokenInvalidError):
        await tokens.verifier().verify("esto.no.es-un-jwt")
