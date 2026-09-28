"""`CurrentPrincipal`: la dependencia obligatoria de todo endpoint de negocio.

Todo endpoint (y el canal SSE) recibe el Principal y filtra por
`principal.organization_id`. No hay otra forma de conocer el tenant.

Códigos:
- 401: sin token o token inválido (firma, emisor, audiencia, expiración, claims básicos).
- 403: token válido pero sin exactamente una organización registrada en Vigía.
- 503: Keycloak no responde al pedir el JWKS.
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vigia.identity.application.authenticate import InvalidClaimsError, authenticate
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
from vigia.shared.web import DbConnection

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
