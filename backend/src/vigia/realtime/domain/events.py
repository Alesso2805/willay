"""Eventos en vivo hacia el panel (VIG-25).

La base avisa por NOTIFY con un JSON (migración 0008). Cada aviso es de una sola
organización y solo se entrega a las conexiones de esa organización (SPEC: el canal SSE
también filtra por organización).

Tipos que recibe el panel:
- `incident`: un incidente cambió (se abrió, escaló, se confirmó...). El panel lo pide
  por REST: así respeta los permisos de quien mira.
- `station`: llegó el latido de una estación, con su último valor.
- `resync`: pudo perderse algún aviso (conexión con la base caída, cliente lento); el
  panel vuelve a pedir todo.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

INCIDENT = "incident"
STATION = "station"
RESYNC = "resync"
KINDS = frozenset({INCIDENT, STATION})


@dataclass(frozen=True)
class RealtimeEvent:
    organization_id: UUID | None  # None solo en `resync`, que va a todas las conexiones
    type: str
    data: Mapping[str, Any] = field(default_factory=dict)


def resync() -> RealtimeEvent:
    return RealtimeEvent(None, RESYNC)


def parse_notification(payload: str) -> RealtimeEvent | None:
    """El evento de un aviso de la base, o None si no se puede leer o no es de un tipo
    conocido: un aviso raro se descarta, nunca tumba la conexión de los demás."""
    try:
        raw = json.loads(payload)
        organization_id = UUID(str(raw.pop("organization_id")))
        kind = raw.pop("type")
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if kind not in KINDS:
        return None
    return RealtimeEvent(organization_id, kind, raw)
