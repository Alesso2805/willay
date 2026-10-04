"""The incident summary for an alert's recipient.

Shared by the dispatcher and the confirmation page so the page never shows different data
from what the message carried. The SQL fragments expect the alert aliased as `a`.
"""

from typing import Any

from sqlalchemy import Row

from willay.alerts.domain.email import AlertMessage
from willay.shared.languages import Language

MESSAGE_COLUMNS = """
    ct.full_name AS contact_name, o.name AS organization_name, o.timezone,
    z.name AS zone_name, i.severity, r.type AS rule_type, s.code AS station_code,
    s.name AS station_name, s.unit, i.trigger_value, i.opened_at, a.level_order,
    COALESCE(ct.language, o.language) AS language
"""

MESSAGE_JOINS = """
    JOIN core.incidents i ON i.id = a.incident_id
    JOIN core.organizations o ON o.id = i.organization_id
    JOIN core.risk_zones z ON z.id = i.zone_id
    JOIN core.rules r ON r.id = i.rule_id
    JOIN core.contacts ct ON ct.id = a.contact_id
    LEFT JOIN core.stations s ON s.id = i.station_id
"""


def message_from_row(r: Row[Any]) -> AlertMessage:
    return AlertMessage(
        contact_name=r.contact_name,
        organization_name=r.organization_name,
        timezone=r.timezone,
        zone_name=r.zone_name,
        severity=r.severity,
        rule_type=r.rule_type,
        station_code=r.station_code,
        station_name=r.station_name,
        unit=r.unit,
        trigger_value=r.trigger_value,
        opened_at=r.opened_at,
        level_order=r.level_order,
        language=Language(r.language),
    )
