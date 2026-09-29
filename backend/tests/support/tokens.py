"""Tokens con la forma de los de Keycloak, firmados con una clave RSA de prueba.

Los tests de pytest no dependen de un Keycloak levantado: verifican nuestra lógica
con tokens controlados. El formato real se comprobó contra Keycloak 26.7.4 (ADR-0004).
"""

from datetime import datetime, timedelta
from functools import cached_property
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from vigia.identity.infrastructure.jwt_verifier import JwtVerifier
from vigia.shared.clock import Clock

ISSUER = "http://keycloak.test/realms/vigia"
AUDIENCE = "vigia-api"

# Usuarios del realm (infra/keycloak/realm-vigia.json).
KC_RIMAC = UUID("1d44f4b3-b1df-457f-b717-20926a20166e")
KC_AISLAMIENTO = UUID("d32ffb77-666e-4986-8234-9f1db8437302")
SUB_RIMAC_ADMIN = UUID("0cd6135c-8fd4-4a14-89f5-cfa4499a71ff")
SUB_RIMAC_OPERATOR = UUID("c144b510-2abd-4844-ad5e-13e700b29fba")
SUB_RIMAC_RESPONDER = UUID("44045649-9897-4e0d-903d-4618194ae7a8")
SUB_RIMAC_VIEWER = UUID("afd7d13d-0556-4190-979a-80e0e36f43d3")
SUB_AISLAMIENTO_ADMIN = UUID("c838d74f-3ec9-4b76-b63c-88e1af475361")
SUB_SIN_ORG = UUID("548d65eb-a1c1-4c67-99f9-a760b203a4e6")
SUB_DOS_ORGS = UUID("6231dd9d-0891-4995-9e09-69832a65c05c")


def org_claim(*orgs: tuple[str, UUID]) -> dict[str, dict[str, str]]:
    return {alias: {"id": str(org_id)} for alias, org_id in orgs}


RIMAC = org_claim(("rimac", KC_RIMAC))
AISLAMIENTO = org_claim(("aislamiento", KC_AISLAMIENTO))


class TokenFactory:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @cached_property
    def public_key(self) -> rsa.RSAPublicKey:
        return self.private_key.public_key()

    def verifier(self) -> JwtVerifier:
        async def resolve(_token: str) -> rsa.RSAPublicKey:
            return self.public_key

        return JwtVerifier(issuer=ISSUER, audience=AUDIENCE, key_resolver=resolve, clock=self.clock)

    def claims(
        self,
        sub: UUID,
        *,
        organization: object = None,
        roles: tuple[str, ...] = ("operator",),
        email: str | None = None,
        lifetime: timedelta = timedelta(minutes=5),
        **overrides: Any,
    ) -> dict[str, Any]:
        now: datetime = self.clock.now()
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(sub),
            "iat": int(now.timestamp()),
            "exp": int((now + lifetime).timestamp()),
            "email": email or f"{sub}@vigia.test",
            "name": f"Usuario {str(sub)[:8]}",
            "realm_access": {"roles": [*roles, "default-roles-vigia"]},
        }
        if organization is not None:
            claims["organization"] = organization
        claims.update(overrides)
        return claims

    def sign(self, claims: dict[str, Any], *, key: Any = None, algorithm: str = "RS256") -> str:
        return jwt.encode(claims, key or self.private_key, algorithm=algorithm)

    def issue(self, sub: UUID, **kwargs: Any) -> str:
        return self.sign(self.claims(sub, **kwargs))
