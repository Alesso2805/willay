"""Keycloak access token verification (RS256 + JWKS).

- Only RS256: prevents `alg: none` and RS256/HS256 confusion (signing with the public key as
  if it were an HMAC secret).
- `iss` and `aud` (vigia-api) are always required.
- `exp` and `nbf` are checked with the injected Clock, not PyJWT's clock, to follow the
  project's time rule and test expiry without real waits.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import jwt

from vigia.shared.clock import Clock

KeyResolver = Callable[[str], Awaitable[Any]]
"""Given the (unverified) token, return the public key that signed it."""

ALGORITHMS = ["RS256"]


class TokenInvalidError(Exception):
    """Token missing, malformed, badly signed, expired or for another issuer/audience (401)."""


class IdentityProviderUnavailableError(Exception):
    """Could not fetch the Keycloak JWKS (503): not the client's fault."""


def jwks_key_resolver(jwks_url: str) -> KeyResolver:
    # PyJWKClient caches the JWKS and refetches on an unknown `kid` (Keycloak key rotation).
    # It is synchronous, so it runs in a thread.
    client = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300, timeout=5)

    async def resolve(token: str) -> Any:
        try:
            signing_key = await asyncio.to_thread(client.get_signing_key_from_jwt, token)
        except jwt.PyJWKClientConnectionError as exc:
            raise IdentityProviderUnavailableError(str(exc)) from exc
        return signing_key.key

    return resolve


class JwtVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        key_resolver: KeyResolver,
        clock: Clock,
        leeway_s: int = 30,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._resolve_key = key_resolver
        self._clock = clock
        self._leeway_s = leeway_s

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            key = await self._resolve_key(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    # Times are checked by _check_times with the injected Clock.
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise TokenInvalidError(str(exc)) from exc
        self._check_times(claims)
        return claims

    def _check_times(self, claims: dict[str, Any]) -> None:
        now = self._clock.now().timestamp()
        exp = claims.get("exp")
        if not isinstance(exp, int | float):
            raise TokenInvalidError("exp is not numeric")
        if now > exp + self._leeway_s:
            raise TokenInvalidError("the token has expired")
        nbf = claims.get("nbf")
        if isinstance(nbf, int | float) and now + self._leeway_s < nbf:
            raise TokenInvalidError("the token is not valid yet")
