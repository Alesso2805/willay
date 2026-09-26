"""API keys de estación: generación, formato y hash Argon2id.

Formato: `<station_id>.<secreto>`. El secreto son 32 bytes aleatorios en base64url
(43 caracteres). El hash Argon2id no se puede buscar, así que el id de la estación
viaja en claro para encontrarla sin probar todos los hashes; lo secreto es solo la
segunda parte. La clave en claro se muestra una vez y nunca se guarda.
"""

import secrets
from dataclasses import dataclass
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_SECRET_BYTES = 32


@dataclass(frozen=True)
class ParsedApiKey:
    station_id: UUID
    secret: str


def generate_api_key(station_id: UUID) -> str:
    return f"{station_id}.{secrets.token_urlsafe(_SECRET_BYTES)}"


def parse_api_key(raw: str) -> ParsedApiKey | None:
    station_part, sep, secret = raw.partition(".")
    if not sep or not secret:
        return None
    try:
        station_id = UUID(station_part)
    except ValueError:
        return None
    return ParsedApiKey(station_id, secret)


class ApiKeyHasher:
    """Argon2id con los parámetros por defecto de argon2-cffi (RFC 9106, perfil bajo en memoria)."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def hash(self, api_key: str) -> str:
        return self._hasher.hash(api_key)

    def verify(self, api_key_hash: str, api_key: str) -> bool:
        try:
            return self._hasher.verify(api_key_hash, api_key)
        except (VerificationError, InvalidHashError):
            return False
