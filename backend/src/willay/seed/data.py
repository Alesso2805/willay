"""Seed data: the Rímac demo organization and the isolation-test organization.

Ids are fixed (uuid v7 generated once) so the seed is idempotent with ON CONFLICT (id) DO
NOTHING. Keycloak ids match infra/keycloak/realm-willay.json.

Demo scenario: damming between Santa Eulalia (upstream) and Chaclacayo (downstream).
Chaclacayo records a sudden discharge drop (rate-of-change rule) and 4 minutes later Santa
Eulalia stops reporting (silence rule). Both rules are in the Chosica zone and use the 3-level
policy.
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
    wkt: str  # MULTIPOLYGON in lon/lat (EPSG:4326)
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
    # (zone_id, position); empty = station without a zone
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


RIMAC = Organization(
    id=_id("01a0dc43-cd2d-7522-8430-867cee8f89ce"),
    keycloak_org_id=_id("1d44f4b3-b1df-457f-b717-20926a20166e"),
    alias="rimac",
    name="Demo Rímac",
)
ISOLATION = Organization(
    id=_id("01a0dc43-cd2d-7522-8430-868cfa60960c"),
    keycloak_org_id=_id("d32ffb77-666e-4986-8234-9f1db8437302"),
    alias="aislamiento",
    name="Prueba de aislamiento",
)
ORGANIZATIONS = (RIMAC, ISOLATION)

Z_CHOSICA = _id("01a0dc43-cd2d-7522-8430-869f7d4b04fa")
Z_CHACLACAYO = _id("01a0dc43-cd2d-7522-8430-86a5bc403e6e")
Z_TEST = _id("01a0dc43-cd2d-7522-8430-86b19d2bd8fc")

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
        Z_TEST,
        ISOLATION.id,
        "Zona de prueba",
        "Zona ficticia para pruebas de aislamiento entre organizaciones",
        "low",
        "MULTIPOLYGON(((-77.200 -11.500, -77.150 -11.500, -77.150 -11.550, "
        "-77.200 -11.550, -77.200 -11.500)))",
        100,
    ),
)

S_SANTA_EULALIA = _id("01a0dc43-cd2d-7522-8430-86ce1fd407cb")
S_CHOSICA_BRIDGE = _id("01a0dc43-cd2d-7522-8430-86d81c73d681")
S_QUIRIO = _id("01a0dc43-cd2d-7522-8430-86e05931cad1")
S_CHACLACAYO = _id("01a0dc43-cd2d-7522-8430-86f295db3dcc")
S_CHACLACAYO_LEVEL = _id("01a0dc43-cd2d-7522-8430-870454b809d0")
S_HUACHIPA = _id("01a0dc43-cd2d-7522-8430-87127602d75c")
S_UNZONED = _id("01a0dc43-cd2d-7522-8430-872e3dade527")
S_AIS_1 = _id("01a0dc43-cd2d-7522-8430-8735f0cc06dc")
S_AIS_2 = _id("01a0dc43-cd2d-7522-8430-87407298a39d")
S_AIS_3 = _id("01a0dc43-cd2d-7522-8430-875a54c68866")

STATIONS = (
    Station(S_SANTA_EULALIA, RIMAC.id, "RIM-SEU-01", "Santa Eulalia (aguas arriba)",
            "discharge", "m3/s", -76.667, -11.902, zones=((Z_CHOSICA, "upstream"),)),
    Station(S_CHOSICA_BRIDGE, RIMAC.id, "RIM-CHO-01", "Chosica, puente",
            "water_level", "m", -76.697, -11.936, zones=((Z_CHOSICA, "in_zone"),)),
    Station(S_QUIRIO, RIMAC.id, "RIM-CHO-02", "Quebrada Quirio",
            "rainfall", "mm", -76.705, -11.925, zones=((Z_CHOSICA, "in_zone"),)),
    Station(S_CHACLACAYO, RIMAC.id, "RIM-CHA-01", "Chaclacayo (aguas abajo)",
            "discharge", "m3/s", -76.764, -11.975,
            zones=((Z_CHOSICA, "downstream"), (Z_CHACLACAYO, "in_zone"))),
    Station(S_CHACLACAYO_LEVEL, RIMAC.id, "RIM-CHA-02", "Chaclacayo, nivel",
            "water_level", "m", -76.780, -11.985, zones=((Z_CHACLACAYO, "in_zone"),)),
    Station(S_HUACHIPA, RIMAC.id, "RIM-HUA-01", "Huachipa",
            "discharge", "m3/s", -76.930, -12.020, zones=((Z_CHACLACAYO, "downstream"),)),
    Station(S_UNZONED, RIMAC.id, "RIM-TMP-01", "Pluviómetro provisional",
            "rainfall", "mm", -76.620, -11.880),
    Station(S_AIS_1, ISOLATION.id, "AIS-01", "Prueba 1",
            "water_level", "m", -77.180, -11.520, zones=((Z_TEST, "in_zone"),)),
    Station(S_AIS_2, ISOLATION.id, "AIS-02", "Prueba 2",
            "rainfall", "mm", -77.170, -11.530, zones=((Z_TEST, "in_zone"),)),
    Station(S_AIS_3, ISOLATION.id, "AIS-03", "Prueba 3",
            "discharge", "m3/s", -77.160, -11.495, zones=((Z_TEST, "upstream"),)),
)  # fmt: skip

C_OPERATOR = _id("01a0dc43-cd2d-7522-8430-8804fa6454d1")
C_BRIGADE = _id("01a0dc43-cd2d-7522-8430-8819717232b6")
C_QUIRIO_LEADER = _id("01a0dc43-cd2d-7522-8430-8823784c9249")
C_HEADQUARTERS = _id("01a0dc43-cd2d-7522-8430-883951381c30")
C_AIS = _id("01a0dc43-cd2d-7522-8430-8843a69f1ba6")

CONTACTS = (
    Contact(C_OPERATOR, RIMAC.id, "Óscar Operador", "operador@rimac.willay.test"),
    Contact(C_BRIGADE, RIMAC.id, "Rosa Brigada", "brigada@rimac.willay.test"),
    Contact(C_QUIRIO_LEADER, RIMAC.id, "Lucho Quispe (líder comunal, Quirio)",
            "lider.quirio@rimac.willay.test"),
    Contact(C_HEADQUARTERS, RIMAC.id, "Carmen Jefatura COE", "jefatura@rimac.willay.test"),
    Contact(C_AIS, ISOLATION.id, "Pablo Operador Aislamiento", "operador@aislamiento.willay.test"),
)  # fmt: skip

G_OPERATORS = _id("01a0dc43-cd2d-7522-8430-87ce6cfb2d92")
G_BRIGADE = _id("01a0dc43-cd2d-7522-8430-87d5abd5c604")
G_HEADQUARTERS = _id("01a0dc43-cd2d-7522-8430-87e5ae247477")
G_TEST_TEAM = _id("01a0dc43-cd2d-7522-8430-87f41b0df5a3")

CONTACT_GROUPS = (
    ContactGroup(G_OPERATORS, RIMAC.id, "Operadores de turno", (C_OPERATOR,)),
    ContactGroup(G_BRIGADE, RIMAC.id, "Brigada Chosica", (C_BRIGADE, C_QUIRIO_LEADER), Z_CHOSICA),
    ContactGroup(G_HEADQUARTERS, RIMAC.id, "Jefatura COE", (C_HEADQUARTERS,)),
    ContactGroup(G_TEST_TEAM, ISOLATION.id, "Equipo de prueba", (C_AIS,)),
)

# Short wait_s so the demo escalates in minutes, not hours.
P_RIMAC = _id("01a0dc43-cd2d-7522-8430-8760070e4d96")
P_ISOLATION = _id("01a0dc43-cd2d-7522-8430-8772cd3ff877")

POLICIES = (
    Policy(P_RIMAC, RIMAC.id, "Protocolo Rímac", (
        Level(_id("01a0dc43-cd2d-7522-8430-878a4114da5a"), 1, 120, (
            (_id("01a0dc46-458d-7463-a383-6531c639a276"), G_OPERATORS, "email"),
        )),
        Level(_id("01a0dc43-cd2d-7522-8430-879d52131694"), 2, 180, (
            (_id("01a0dc46-458d-7463-a383-654213970d9d"), G_BRIGADE, "telegram"),
            (_id("01a0dc46-458d-7463-a383-655ed8b6378e"), G_BRIGADE, "email"),
        )),
        Level(_id("01a0dc43-cd2d-7522-8430-87a2790e47d5"), 3, 300, (
            (_id("01a0dc46-458d-7463-a383-6563859e6bcd"), G_HEADQUARTERS, "email"),
            (_id("01a0dc46-458d-7463-a383-65722e96813d"), G_HEADQUARTERS, "telegram"),
        )),
    )),
    Policy(P_ISOLATION, ISOLATION.id, "Protocolo de prueba", (
        Level(_id("01a0dc43-cd2d-7522-8430-87b4e11341e4"), 1, 300, (
            (_id("01a0dc46-458d-7463-a383-6581f5d66925"), G_TEST_TEAM, "email"),
        )),
    )),
)  # fmt: skip

RULES = (
    # Demo: sudden downstream discharge drop (possible damming).
    Rule(_id("01a0dc43-cd2d-7522-8430-885b797ba5ab"), RIMAC.id, Z_CHOSICA, S_CHACLACAYO,
         "rate_of_change", "critical", P_RIMAC, 1800,
         {"direction": "down", "delta": 40.0, "window_minutes": 10}),
    # Demo: the upstream station stops reporting.
    Rule(_id("01a0dc43-cd2d-7522-8430-88678c1c9e40"), RIMAC.id, Z_CHOSICA, S_SANTA_EULALIA,
         "silence", "critical", P_RIMAC, 1800),
    Rule(_id("01a0dc43-cd2d-7522-8430-887dff49bcda"), RIMAC.id, Z_CHOSICA, S_CHOSICA_BRIDGE,
         "threshold", "warning", P_RIMAC, 1800,
         {"operator": "gt", "value": 3.5, "consecutive": 2}),
    Rule(_id("01a0dc43-cd2d-7522-8430-8881d3a00c0a"), RIMAC.id, Z_CHOSICA, S_QUIRIO,
         "threshold", "warning", P_RIMAC, 3600,
         {"operator": "gt", "value": 20.0, "consecutive": 3}),
    # Null station_id: applies to every station in the zone.
    Rule(_id("01a0dc46-458d-7463-a383-6593a8ef5e95"), RIMAC.id, Z_CHACLACAYO, None,
         "silence", "warning", P_RIMAC, 1800),
    Rule(_id("01a0dc46-458d-7463-a383-65a9a88d03ea"), ISOLATION.id, Z_TEST, S_AIS_1,
         "threshold", "warning", P_ISOLATION, 600,
         {"operator": "gt", "value": 5.0, "consecutive": 2}),
)  # fmt: skip
