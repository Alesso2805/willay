"""Regla de sensor silencioso (VIG-17): una estación que dejó de reportar.

Una estación está en silencio cuando pasaron al menos K * expected_interval_s desde su
último latido (`station_heartbeats.last_seen_at`, el último lote con alguna lectura no
tardía). K sale solo de `stations.silence_multiplier` (SPEC): la regla no tiene
parámetros, así una estación tiene el mismo umbral en todas las reglas que la vigilan.

Una estación que nunca reportó no está en silencio: todavía no empezó a transmitir, y
contarla haría que un stack recién sembrado abriera incidentes antes de recibir datos.
"""

from datetime import datetime, timedelta


def silence_threshold(expected_interval_s: int, multiplier: int) -> timedelta:
    return timedelta(seconds=expected_interval_s * multiplier)


def is_silent(last_seen_at: datetime | None, threshold: timedelta, now: datetime) -> bool:
    return last_seen_at is not None and now - last_seen_at >= threshold
