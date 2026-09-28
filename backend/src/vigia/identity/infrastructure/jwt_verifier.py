"""Verificación de access tokens de Keycloak (RS256 + JWKS).

- Solo se acepta RS256: evita `alg: none` y la confusión RS256/HS256 (firmar con la
  clave pública como si fuera un secreto HMAC).
- `iss` y `aud` (vigia-api) se exigen siempre.
- `exp` y `nbf` se comprueban con el Clock inyectado, no con el reloj de PyJWT, para
  cumplir la regla de tiempo del proyecto y probar la expiración sin esperas reales.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import jwt

from vigia.shared.clock import Clock

KeyResolver = Callable[[str], Awaitable[Any]]
"""Dado el token (sin verificar), devuelve la clave pública que lo firmó."""

ALGORITHMS = ["RS256"]


class TokenInvalidError(Exception):
    """Token ausente, mal formado, mal firmado, expirado o para otro emisor/audiencia (401)."""


class IdentityProviderUnavailableError(Exception):
    """No se pudo descargar el JWKS de Keycloak (503): no es culpa del cliente."""


def jwks_key_resolver(jwks_url: str) -> KeyResolver:
    # PyJWKClient cachea el JWKS y lo vuelve a pedir si llega un `kid` desconocido
    # (rotación de claves en Keycloak). Es síncrono: se ejecuta en un hilo.
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
                    # El tiempo lo comprueba _check_times con el Clock inyectado.
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
            raise TokenInvalidError("exp no es numérico")
        if now > exp + self._leeway_s:
            raise TokenInvalidError("el token expiró")
        nbf = claims.get("nbf")
        if isinstance(nbf, int | float) and now + self._leeway_s < nbf:
            raise TokenInvalidError("el token aún no es válido")
