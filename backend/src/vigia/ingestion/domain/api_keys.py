"""Formato de las API keys de estación: `<station_id>.<secreto>`.

El secreto son 32 bytes aleatorios en base64url (43 caracteres). El id de la estación
viaja en claro para encontrarla sin probar todos los hashes (Argon2id no se puede
buscar); lo secreto es solo la segunda parte. La clave en claro se muestra una vez y
nunca se guarda: solo su hash (ver infrastructure/api_keys.py).
"""

import secrets
from dataclasses import dataclass
from uuid import UUID

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
