"""Hash Argon2id de las API keys de estación (el formato vive en domain/api_keys.py)."""

from functools import cached_property
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from vigia.ingestion.domain.api_keys import generate_api_key


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

    @cached_property
    def dummy_hash(self) -> str:
        """Hash de una clave que nadie tiene, con los mismos parámetros que los reales.

        Verificar contra él cuando la estación no existe iguala el tiempo de respuesta.
        """
        return self._hasher.hash("vigia-dummy-key-que-nunca-coincide")


class Argon2ApiKeyIssuer:
    """Emite claves para el módulo de territorio (crear estación, rotar clave)."""

    def __init__(self, hasher: ApiKeyHasher) -> None:
        self._hasher = hasher

    def issue(self, station_id: UUID) -> tuple[str, str]:
        api_key = generate_api_key(station_id)
        return api_key, self._hasher.hash(api_key)
