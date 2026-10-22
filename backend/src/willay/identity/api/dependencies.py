"""`CurrentPrincipal`: the mandatory dependency of every business endpoint.

Every endpoint (and the SSE channel) receives the Principal and filters by
`principal.organization_id`; there is no other way to learn the tenant.

- 401: missing or invalid token (signature, issuer, audience, expiry, basic claims).
- 403: valid token without exactly one organization registered in Willay, or (with `require`)
  roles lacking the endpoint's permission.
- 503: Keycloak does not answer the JWKS request.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from willay.identity.application.authenticate import InvalidClaimsError, authenticate
from willay.identity.domain.permissions import Permission, can
from willay.identity.domain.principal import Principal, TenantError
from willay.identity.infrastructure.jwt_verifier import (
    IdentityProviderUnavailableError,
    JwtVerifier,
    TokenInvalidError,
)
from willay.identity.infrastructure.repositories import (
    SqlOrganizationRepository,
    SqlUserRepository,
)
from willay.shared.errors import ErrorCode
from willay.shared.web import ApiError, DbConnection, EngineDep

# auto_error=False: we answer 401 with WWW-Authenticate ourselves (FastAPI would send 403).
_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = ApiError(
    status.HTTP_401_UNAUTHORIZED,
    ErrorCode.TOKEN_INVALID,
    headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
)
_FORBIDDEN_TENANT = ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.ORGANIZATION_REQUIRED)


def get_verifier(request: Request) -> JwtVerifier:
    verifier: JwtVerifier = request.app.state.verifier
    return verifier


async def verified_claims(
    verifier: Annotated[JwtVerifier, Depends(get_verifier)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict[str, Any]:
    # Separate from current_principal so invalid tokens are rejected without taking a pool
    # connection: FastAPI resolves dependencies in declaration order.
    if credentials is None:
        raise _UNAUTHORIZED
    try:
        return await verifier.verify(credentials.credentials)
    except TokenInvalidError as exc:
        raise _UNAUTHORIZED from exc
    except IdentityProviderUnavailableError as exc:
        raise ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.IDENTITY_UNAVAILABLE) from exc


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
    """Dependency requiring a permission from the matrix. Usage in an endpoint:

        principal: Annotated[Principal, Depends(require(Permission.MANAGE_RULES))]

    Returns the same Principal, so the endpoint still has the tenant.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        _ensure(principal, permission)
        return principal

    return dependency


def _ensure(principal: Principal, permission: Permission) -> None:
    if not can(principal, permission):
        # Its own code (permission_denied), apart from the tenant 403 (organization_required),
        # so a client can tell them apart.
        raise ApiError(
            status.HTTP_403_FORBIDDEN, ErrorCode.PERMISSION_DENIED, permission=permission.value
        )


@dataclass(frozen=True)
class StreamGrant:
    principal: Principal
    expires_at: datetime  # the token's `exp`: the stream does not outlive its token


async def stream_grant(
    claims: Annotated[dict[str, Any], Depends(verified_claims)],
    engine: EngineDep,
) -> StreamGrant:
    """Authentication for long-lived responses (SSE).

    `current_principal` uses the request transaction, which in a stream would live as long as
    the connection: one pool connection held per open dashboard. This authenticates in a short
    transaction that ends before streaming starts.
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
