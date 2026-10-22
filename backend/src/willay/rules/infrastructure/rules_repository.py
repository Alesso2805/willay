"""RuleRepository over core.rules."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncConnection

from willay.incidents.domain.severity import Severity
from willay.rules.application.rules import Ref, Rule, StationRef
from willay.rules.domain.rules import RuleData, RuleType

_SELECT = """
    SELECT r.id, r.type, r.zone_id, z.name AS zone_name, r.station_id,
           s.code AS station_code, s.name AS station_name, s.unit AS station_unit,
           r.params, r.severity, r.escalation_policy_id, p.name AS policy_name,
           r.cooldown_s, r.is_active, r.created_at, r.updated_at
    FROM core.rules r
    JOIN core.risk_zones z ON z.id = r.zone_id
    JOIN core.escalation_policies p ON p.id = r.escalation_policy_id
    LEFT JOIN core.stations s ON s.id = r.station_id
    WHERE r.organization_id = :organization_id
"""
_ORDER = " ORDER BY z.name, r.type, s.code NULLS FIRST, r.id"

_ALL = text(_SELECT + " AND (r.is_active OR :include_inactive)" + _ORDER)
_GET = text(_SELECT + " AND r.id = :id")
_GET_FOR_UPDATE = text(_SELECT + " AND r.id = :id FOR UPDATE OF r")

_ZONE_EXISTS = text("""
    SELECT EXISTS (SELECT 1 FROM core.risk_zones
                   WHERE organization_id = :organization_id AND id = :id)
""")
_STATION_IN_ZONE = text("""
    SELECT EXISTS (SELECT 1 FROM core.stations s
                   JOIN core.zone_stations zs ON zs.station_id = s.id
                   WHERE s.organization_id = :organization_id AND s.id = :station_id
                     AND zs.zone_id = :zone_id)
""")
_POLICY_EXISTS = text("""
    SELECT EXISTS (SELECT 1 FROM core.escalation_policies
                   WHERE organization_id = :organization_id AND id = :id)
""")

_ADD = text("""
    INSERT INTO core.rules (id, organization_id, zone_id, station_id, type, params, severity,
                            escalation_policy_id, cooldown_s, is_active, created_by,
                            created_at, updated_at)
    VALUES (:id, :organization_id, :zone_id, :station_id, :type, CAST(:params AS jsonb),
            :severity, :escalation_policy_id, :cooldown_s, :is_active, :created_by, :now, :now)
""")
_REPLACE = text("""
    UPDATE core.rules
    SET zone_id = :zone_id, station_id = :station_id, params = CAST(:params AS jsonb),
        severity = :severity, escalation_policy_id = :escalation_policy_id,
        cooldown_s = :cooldown_s, is_active = :is_active, updated_at = :now
    WHERE organization_id = :organization_id AND id = :id
""")


class SqlRuleAdminRepository:
    """The rules as the operator manages them; the evaluator has its own narrower queries."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def all_of(self, organization_id: UUID, *, include_inactive: bool) -> list[Rule]:
        rows = await self._conn.execute(
            _ALL, {"organization_id": organization_id, "include_inactive": include_inactive}
        )
        return [_rule(r) for r in rows]

    async def get(
        self, organization_id: UUID, rule_id: UUID, *, for_update: bool = False
    ) -> Rule | None:
        query = _GET_FOR_UPDATE if for_update else _GET
        row = (
            await self._conn.execute(query, {"organization_id": organization_id, "id": rule_id})
        ).first()
        return _rule(row) if row is not None else None

    async def zone_exists(self, organization_id: UUID, zone_id: UUID) -> bool:
        params = {"organization_id": organization_id, "id": zone_id}
        return bool(await self._conn.scalar(_ZONE_EXISTS, params))

    async def station_in_zone(self, organization_id: UUID, station_id: UUID, zone_id: UUID) -> bool:
        params = {"organization_id": organization_id, "station_id": station_id, "zone_id": zone_id}
        return bool(await self._conn.scalar(_STATION_IN_ZONE, params))

    async def policy_exists(self, organization_id: UUID, policy_id: UUID) -> bool:
        params = {"organization_id": organization_id, "id": policy_id}
        return bool(await self._conn.scalar(_POLICY_EXISTS, params))

    async def add(
        self,
        rule_id: UUID,
        organization_id: UUID,
        rule_type: RuleType,
        data: RuleData,
        created_by: UUID,
        now: datetime,
    ) -> Rule:
        await self._conn.execute(
            _ADD,
            {
                "id": rule_id,
                "organization_id": organization_id,
                "type": rule_type.value,
                "created_by": created_by,
                "now": now,
                **_columns(data),
            },
        )
        return await self._reload(organization_id, rule_id)

    async def replace(
        self, organization_id: UUID, rule_id: UUID, data: RuleData, now: datetime
    ) -> Rule:
        await self._conn.execute(
            _REPLACE,
            {"organization_id": organization_id, "id": rule_id, "now": now, **_columns(data)},
        )
        return await self._reload(organization_id, rule_id)

    async def _reload(self, organization_id: UUID, rule_id: UUID) -> Rule:
        rule = await self.get(organization_id, rule_id)
        if rule is None:  # impossible within the same transaction
            raise LookupError(rule_id)
        return rule


def _columns(data: RuleData) -> dict[str, Any]:
    return {
        "zone_id": data.zone_id,
        "station_id": data.station_id,
        "params": json.dumps(dict(data.params)),
        "severity": data.severity.value,
        "escalation_policy_id": data.escalation_policy_id,
        "cooldown_s": data.cooldown_s,
        "is_active": data.is_active,
    }


def _rule(r: Row[Any]) -> Rule:
    station = (
        StationRef(r.station_id, r.station_code, r.station_name, r.station_unit)
        if r.station_id is not None
        else None
    )
    return Rule(
        id=r.id,
        type=RuleType(r.type),
        data=RuleData(
            zone_id=r.zone_id,
            station_id=r.station_id,
            params=r.params,
            severity=Severity(r.severity),
            escalation_policy_id=r.escalation_policy_id,
            cooldown_s=r.cooldown_s,
            is_active=r.is_active,
        ),
        zone=Ref(r.zone_id, r.zone_name),
        station=station,
        policy=Ref(r.escalation_policy_id, r.policy_name),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )
