"""Datos semilla: organización demo Rímac y organización de aislamiento.

Los ids son fijos (uuid v7 generados una vez) para que el seed sea idempotente con
ON CONFLICT (id) DO NOTHING. Los ids de Keycloak coinciden con infra/keycloak/realm-vigia.json.

Escenario de demo: represamiento entre Santa Eulalia (aguas arriba) y Chaclacayo
(aguas abajo). Chaclacayo registra una caída brusca de caudal (regla de tasa de cambio)
y 4 minutos después Santa Eulalia deja de reportar (regla de silencio). Ambas reglas
están en la zona Chosica y usan la política de 3 niveles.
"""

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class Organization:
    id: UUID
    keycloak_org_id: UUID
    alias: str
    name: str
    timezone: str = "America/Lima"


@dataclass(frozen=True)
class Zone:
    id: UUID
    organization_id: UUID
    name: str
    description: str
    risk_level: str
    wkt: str  # MULTIPOLYGON en lon/lat (EPSG:4326)
    population_estimate: int


@dataclass(frozen=True)
class Station:
    id: UUID
    organization_id: UUID
    code: str
    name: str
    variable: str
    unit: str
    lon: float
    lat: float
    expected_interval_s: int = 10
    silence_multiplier: int = 3
    source: str = "simulator"
    # (zone_id, position); vacío = estación sin zona
    zones: tuple[tuple[UUID, str], ...] = ()


@dataclass(frozen=True)
class Contact:
    id: UUID
    organization_id: UUID
    full_name: str
    email: str


@dataclass(frozen=True)
class ContactGroup:
    id: UUID
    organization_id: UUID
    name: str
    members: tuple[UUID, ...]
    zone_id: UUID | None = None


@dataclass(frozen=True)
class Level:
    id: UUID
    level_order: int
    wait_s: int
    # (target_id, contact_group_id, channel)
    targets: tuple[tuple[UUID, UUID, str], ...]


@dataclass(frozen=True)
class Policy:
    id: UUID
    organization_id: UUID
    name: str
    levels: tuple[Level, ...]


@dataclass(frozen=True)
class Rule:
    id: UUID
    organization_id: UUID
    zone_id: UUID
    station_id: UUID | None
    type: str
    severity: str
    escalation_policy_id: UUID
    cooldown_s: int
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def params_json(self) -> str:
        return json.dumps(self.params)


def _id(value: str) -> UUID:
    return UUID(value)


# --- Organizaciones ---------------------------------------------------------------
RIMAC = Organization(
    id=_id("01a0dc43-cd2d-7522-8430-867cee8f89ce"),
    keycloak_org_id=_id("1d44f4b3-b1df-457f-b717-20926a20166e"),
    alias="rimac",
    name="Demo Rímac",
)
AISLAMIENTO = Organization(
    id=_id("01a0dc43-cd2d-7522-8430-868cfa60960c"),
    keycloak_org_id=_id("d32ffb77-666e-4986-8234-9f1db8437302"),
    alias="aislamiento",
    name="Prueba de aislamiento",
)
ORGANIZATIONS = (RIMAC, AISLAMIENTO)

# --- Zonas ------------------------------------------------------------------------
Z_CHOSICA = _id("01a0dc43-cd2d-7522-8430-869f7d4b04fa")
Z_CHACLACAYO = _id("01a0dc43-cd2d-7522-8430-86a5bc403e6e")
Z_PRUEBA = _id("01a0dc43-cd2d-7522-8430-86b19d2bd8fc")

ZONES = (
    Zone(
        Z_CHOSICA,
        RIMAC.id,
        "Chosica",
        "Cauce del Rímac y quebradas activas de Chosica (Quirio, Pedregal)",
        "critical",
        "MULTIPOLYGON(((-76.725 -11.905, -76.665 -11.905, -76.665 -11.955, "
        "-76.725 -11.955, -76.725 -11.905)))",
        45000,
    ),
    Zone(
        Z_CHACLACAYO,
        RIMAC.id,
        "Chaclacayo",
        "Riberas del Rímac en Chaclacayo",
        "high",
        "MULTIPOLYGON(((-76.800 -11.960, -76.735 -11.960, -76.735 -12.000, "
        "-76.800 -12.000, -76.800 -11.960)))",
        30000,
    ),
    Zone(
        Z_PRUEBA,
        AISLAMIENTO.id,
        "Zona de prueba",
        "Zona ficticia para pruebas de aislamiento entre organizaciones",
        "low",
        "MULTIPOLYGON(((-77.200 -11.500, -77.150 -11.500, -77.150 -11.550, "
        "-77.200 -11.550, -77.200 -11.500)))",
        100,
    ),
)

# --- Estaciones (7 Rímac + 3 aislamiento) -----------------------------------------
S_SANTA_EULALIA = _id("01a0dc43-cd2d-7522-8430-86ce1fd407cb")
S_CHOSICA_PUENTE = _id("01a0dc43-cd2d-7522-8430-86d81c73d681")
S_QUIRIO = _id("01a0dc43-cd2d-7522-8430-86e05931cad1")
S_CHACLACAYO = _id("01a0dc43-cd2d-7522-8430-86f295db3dcc")
S_CHACLACAYO_NIVEL = _id("01a0dc43-cd2d-7522-8430-870454b809d0")
S_HUACHIPA = _id("01a0dc43-cd2d-7522-8430-87127602d75c")
S_SIN_ZONA = _id("01a0dc43-cd2d-7522-8430-872e3dade527")
S_AIS_1 = _id("01a0dc43-cd2d-7522-8430-8735f0cc06dc")
S_AIS_2 = _id("01a0dc43-cd2d-7522-8430-87407298a39d")
S_AIS_3 = _id("01a0dc43-cd2d-7522-8430-875a54c68866")

STATIONS = (
    Station(S_SANTA_EULALIA, RIMAC.id, "RIM-SEU-01", "Santa Eulalia (aguas arriba)",
            "discharge", "m3/s", -76.667, -11.902, zones=((Z_CHOSICA, "upstream"),)),
    Station(S_CHOSICA_PUENTE, RIMAC.id, "RIM-CHO-01", "Chosica, puente",
            "water_level", "m", -76.697, -11.936, zones=((Z_CHOSICA, "in_zone"),)),
    Station(S_QUIRIO, RIMAC.id, "RIM-CHO-02", "Quebrada Quirio",
            "rainfall", "mm", -76.705, -11.925, zones=((Z_CHOSICA, "in_zone"),)),
    Station(S_CHACLACAYO, RIMAC.id, "RIM-CHA-01", "Chaclacayo (aguas abajo)",
            "discharge", "m3/s", -76.764, -11.975,
            zones=((Z_CHOSICA, "downstream"), (Z_CHACLACAYO, "in_zone"))),
    Station(S_CHACLACAYO_NIVEL, RIMAC.id, "RIM-CHA-02", "Chaclacayo, nivel",
            "water_level", "m", -76.780, -11.985, zones=((Z_CHACLACAYO, "in_zone"),)),
    Station(S_HUACHIPA, RIMAC.id, "RIM-HUA-01", "Huachipa",
            "discharge", "m3/s", -76.930, -12.020, zones=((Z_CHACLACAYO, "downstream"),)),
    Station(S_SIN_ZONA, RIMAC.id, "RIM-TMP-01", "Estación sin asignar",
            "rainfall", "mm", -76.620, -11.880),
    Station(S_AIS_1, AISLAMIENTO.id, "AIS-01", "Prueba 1",
            "water_level", "m", -77.180, -11.520, zones=((Z_PRUEBA, "in_zone"),)),
    Station(S_AIS_2, AISLAMIENTO.id, "AIS-02", "Prueba 2",
            "rainfall", "mm", -77.170, -11.530, zones=((Z_PRUEBA, "in_zone"),)),
    Station(S_AIS_3, AISLAMIENTO.id, "AIS-03", "Prueba 3",
            "discharge", "m3/s", -77.160, -11.495, zones=((Z_PRUEBA, "upstream"),)),
)  # fmt: skip

# --- Contactos y grupos (4 Rímac + 1 aislamiento) ---------------------------------
C_OPERADOR = _id("01a0dc43-cd2d-7522-8430-8804fa6454d1")
C_BRIGADA = _id("01a0dc43-cd2d-7522-8430-8819717232b6")
C_LIDER_QUIRIO = _id("01a0dc43-cd2d-7522-8430-8823784c9249")
C_JEFATURA = _id("01a0dc43-cd2d-7522-8430-883951381c30")
C_AIS = _id("01a0dc43-cd2d-7522-8430-8843a69f1ba6")

CONTACTS = (
    Contact(C_OPERADOR, RIMAC.id, "Óscar Operador", "operador@rimac.vigia.test"),
    Contact(C_BRIGADA, RIMAC.id, "Rosa Brigada", "brigada@rimac.vigia.test"),
    Contact(C_LIDER_QUIRIO, RIMAC.id, "Lucho Quispe (líder comunal, Quirio)",
            "lider.quirio@rimac.vigia.test"),
    Contact(C_JEFATURA, RIMAC.id, "Carmen Jefatura COE", "jefatura@rimac.vigia.test"),
    Contact(C_AIS, AISLAMIENTO.id, "Pablo Operador Aislamiento", "operador@aislamiento.vigia.test"),
)  # fmt: skip

G_OPERADORES = _id("01a0dc43-cd2d-7522-8430-87ce6cfb2d92")
G_BRIGADA = _id("01a0dc43-cd2d-7522-8430-87d5abd5c604")
G_JEFATURA = _id("01a0dc43-cd2d-7522-8430-87e5ae247477")
G_EQUIPO_PRUEBA = _id("01a0dc43-cd2d-7522-8430-87f41b0df5a3")

CONTACT_GROUPS = (
    ContactGroup(G_OPERADORES, RIMAC.id, "Operadores de turno", (C_OPERADOR,)),
    ContactGroup(G_BRIGADA, RIMAC.id, "Brigada Chosica", (C_BRIGADA, C_LIDER_QUIRIO), Z_CHOSICA),
    ContactGroup(G_JEFATURA, RIMAC.id, "Jefatura COE", (C_JEFATURA,)),
    ContactGroup(G_EQUIPO_PRUEBA, AISLAMIENTO.id, "Equipo de prueba", (C_AIS,)),
)

# --- Políticas de escalamiento (una por organización) -----------------------------
# wait_s cortos para que la demo escale en minutos, no en horas.
P_RIMAC = _id("01a0dc43-cd2d-7522-8430-8760070e4d96")
P_AISLAMIENTO = _id("01a0dc43-cd2d-7522-8430-8772cd3ff877")

POLICIES = (
    Policy(P_RIMAC, RIMAC.id, "Protocolo Rímac", (
        Level(_id("01a0dc43-cd2d-7522-8430-878a4114da5a"), 1, 120, (
            (_id("01a0dc46-458d-7463-a383-6531c639a276"), G_OPERADORES, "email"),
        )),
        Level(_id("01a0dc43-cd2d-7522-8430-879d52131694"), 2, 180, (
            (_id("01a0dc46-458d-7463-a383-654213970d9d"), G_BRIGADA, "telegram"),
            (_id("01a0dc46-458d-7463-a383-655ed8b6378e"), G_BRIGADA, "email"),
        )),
        Level(_id("01a0dc43-cd2d-7522-8430-87a2790e47d5"), 3, 300, (
            (_id("01a0dc46-458d-7463-a383-6563859e6bcd"), G_JEFATURA, "email"),
            (_id("01a0dc46-458d-7463-a383-65722e96813d"), G_JEFATURA, "telegram"),
        )),
    )),
    Policy(P_AISLAMIENTO, AISLAMIENTO.id, "Protocolo de prueba", (
        Level(_id("01a0dc43-cd2d-7522-8430-87b4e11341e4"), 1, 300, (
            (_id("01a0dc46-458d-7463-a383-6581f5d66925"), G_EQUIPO_PRUEBA, "email"),
        )),
    )),
)  # fmt: skip

# --- Reglas (5 Rímac + 1 aislamiento) ---------------------------------------------
RULES = (
    # Demo: caída brusca de caudal aguas abajo (posible represamiento).
    Rule(_id("01a0dc43-cd2d-7522-8430-885b797ba5ab"), RIMAC.id, Z_CHOSICA, S_CHACLACAYO,
         "rate_of_change", "critical", P_RIMAC, 1800,
         {"direction": "down", "delta": 40.0, "window_minutes": 10}),
    # Demo: la estación aguas arriba deja de reportar.
    Rule(_id("01a0dc43-cd2d-7522-8430-88678c1c9e40"), RIMAC.id, Z_CHOSICA, S_SANTA_EULALIA,
         "silence", "critical", P_RIMAC, 1800),
    Rule(_id("01a0dc43-cd2d-7522-8430-887dff49bcda"), RIMAC.id, Z_CHOSICA, S_CHOSICA_PUENTE,
         "threshold", "warning", P_RIMAC, 1800,
         {"operator": "gt", "value": 3.5, "consecutive": 2}),
    Rule(_id("01a0dc43-cd2d-7522-8430-8881d3a00c0a"), RIMAC.id, Z_CHOSICA, S_QUIRIO,
         "threshold", "warning", P_RIMAC, 3600,
         {"operator": "gt", "value": 20.0, "consecutive": 3}),
    # station_id nulo: aplica a todas las estaciones de la zona.
    Rule(_id("01a0dc46-458d-7463-a383-6593a8ef5e95"), RIMAC.id, Z_CHACLACAYO, None,
         "silence", "warning", P_RIMAC, 1800),
    Rule(_id("01a0dc46-458d-7463-a383-65a9a88d03ea"), AISLAMIENTO.id, Z_PRUEBA, S_AIS_1,
         "threshold", "warning", P_AISLAMIENTO, 600,
         {"operator": "gt", "value": 5.0, "consecutive": 2}),
)  # fmt: skip
