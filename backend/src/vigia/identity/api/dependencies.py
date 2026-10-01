"""`CurrentPrincipal`: la dependencia obligatoria de todo endpoint de negocio.

Todo endpoint (y el canal SSE) recibe el Principal y filtra por
`principal.organization_id`. No hay otra forma de conocer el tenant.

Códigos:
- 401: sin token o token inválido (firma, emisor, audiencia, expiración, claims básicos).
- 403: token válido pero sin exactamente una organización registrada en Vigía, o
  (con `require`) un rol sin el permiso que pide el endpoint.
- 503: Keycloak no responde al pedir el JWKS.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vigia.identity.application.authenticate import InvalidClaimsError, authenticate
from vigia.identity.domain.permissions import Permission, can
from vigia.identity.domain.principal import Principal, TenantError
from vigia.identity.infrastructure.jwt_verifier import (
    IdentityProviderUnavailableError,
    JwtVerifier,
    TokenInvalidError,
)
from vigia.identity.infrastructure.repositories import (
    SqlOrganizationRepository,
    SqlUserRepository,
)
from vigia.shared.web import DbConnection, EngineDep

# auto_error=False: respondemos nosotros el 401 con WWW-Authenticate (FastAPI daría 403).
_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    detail="Token ausente o inválido",
    headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
)
_FORBIDDEN_TENANT = HTTPException(
    status.HTTP_403_FORBIDDEN,
    detail="El usuario debe pertenecer a exactamente una organización registrada en Vigía",
)


def get_verifier(request: Request) -> JwtVerifier:
    verifier: JwtVerifier = request.app.state.verifier
    return verifier


async def verified_claims(
    verifier: Annotated[JwtVerifier, Depends(get_verifier)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any]:
    # Separada de current_principal para rechazar tokens inválidos sin tomar una
    # conexión del pool: FastAPI resuelve las dependencias en orden de declaración.
    if credentials is None:
        raise _UNAUTHORIZED
    try:
        return await verifier.verify(credentials.credentials)
    except TokenInvalidError as exc:
        raise _UNAUTHORIZED from exc
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Proveedor de identidad no disponible"
        ) from exc


async def current_principal(
    claims: Annotated[dict[str, Any], Depends(verified_claims)],
    conn: DbConnection,
) -> Principal:
    try:
        return await authenticate(claims, SqlOrganizationRepository(conn), SqlUserRepository(conn))
    except InvalidClaimsError as exc:
        raise _UNAUTHORIZED from exc
    except TenantError as exc:
        raise _FORBIDDEN_TENANT from exc


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependencia que exige un permiso de la matriz. Uso en un endpoint:

        principal: Annotated[Principal, Depends(require(Permission.MANAGE_RULES))]

    Devuelve el mismo Principal, así el endpoint sigue teniendo el tenant.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        _ensure(principal, permission)
        return principal

    return dependency


def _ensure(principal: Principal, permission: Permission) -> None:
    if not can(principal, permission):
        # Mensaje distinto del 403 de tenant: el panel puede explicar cuál de los dos es.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"Tu rol no tiene el permiso {permission}"
        )


@dataclass(frozen=True)
class StreamGrant:
    principal: Principal
    expires_at: datetime  # el `exp` del token: el stream no sobrevive a su token


async def stream_grant(
    claims: Annotated[dict[str, Any], Depends(verified_claims)],
    engine: EngineDep,
) -> StreamGrant:
    """Autenticación para respuestas largas (SSE, VIG-25).

    `current_principal` usa la transacción de la petición, y en un stream esa transacción
    viviría lo que dure la conexión: una conexión del pool ocupada por cada panel abierto.
    Aquí se autentica en una transacción corta que termina antes de transmitir.
    """
    async with engine.begin() as conn:
        try:
            principal = await authenticate(
                claims, SqlOrganizationRepository(conn), SqlUserRepository(conn)
            )
        except InvalidClaimsError as exc:
            raise _UNAUTHORIZED from exc
        except TenantError as exc:
            raise _FORBIDDEN_TENANT from exc
    _ensure(principal, Permission.VIEW)
    try:
        expires_at = datetime.fromtimestamp(int(claims["exp"]), UTC)
    except (KeyError, TypeError, ValueError) as exc:
        raise _UNAUTHORIZED from exc
    return StreamGrant(principal, expires_at)


StreamGrantDep = Annotated[StreamGrant, Depends(stream_grant)]
