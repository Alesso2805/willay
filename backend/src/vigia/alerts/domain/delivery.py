"""Entrega de alertas: reintentos y token de confirmación (SPEC: Alertas, NFR Fiabilidad).

Reintentos: un envío fallido se reintenta 3 veces con espera exponencial (5, 10 y 20 s).
Al cuarto intento fallido la alerta queda `failed`. En un sistema de alertas es preferible
un correo duplicado a uno perdido, así que un envío cuyo resultado no llegó a guardarse
(el worker murió) se vuelve a intentar.

Token de confirmación: 256 bits aleatorios en base64url (43 caracteres, cabe en los 64
de `callback_data` de Telegram). Se guarda solo su SHA-256: con 256 bits de azar no hace
falta un hash lento como Argon2 (no hay diccionario que probar), y quien lea la base no
puede confirmar alertas. Vale 24 h y es de un solo uso (lo aplica VIG-23).
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_ATTEMPTS = 4  # el envío original y 3 reintentos
FIRST_RETRY = timedelta(seconds=5)
TOKEN_BYTES = 32
TOKEN_TTL = timedelta(hours=24)


def retry_at(failed_attempt: int, now: datetime) -> datetime | None:
    """Cuándo reintentar tras fallar el intento `failed_attempt` (1, 2, ...); None si era el
    último."""
    if failed_attempt >= MAX_ATTEMPTS:
        return None
    return now + FIRST_RETRY * int(2 ** (failed_attempt - 1))  # 5, 10, 20 s


@dataclass(frozen=True)
class AckToken:
    token: str  # solo viaja en el mensaje; nunca se guarda
    token_hash: str
    expires_at: datetime


def new_ack_token(now: datetime) -> AckToken:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return AckToken(token, hash_ack_token(token), now + TOKEN_TTL)


def hash_ack_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()
