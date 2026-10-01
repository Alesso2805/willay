"""Alert confirmation pages (VIG-23): plain HTML, no JavaScript.

Opened from email, sometimes on a modest phone: a light page that works without scripts
and is accessible (state is stated in text, never by color alone). All variable data is
escaped.
"""

from html import escape

from willay.alerts.application.confirmation import AlertToConfirm, ConfirmationView
from willay.alerts.domain.confirmation import ConfirmOutcome
from willay.alerts.domain.email import local_time, summary
from willay.incidents.domain.lifecycle import IncidentStatus

# Inline styles: these pages' CSP allows no external resources.
_STYLE = """
body { font-family: system-ui, sans-serif; color: #1b1b1b; background: #fff;
       max-width: 34rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
h1 { font-size: 1.4rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1rem; }
dt { font-weight: 600; }
dd { margin: 0; }
button { font-size: 1.1rem; padding: .75rem 1.25rem; border: 0; border-radius: .4rem;
         background: #0b4f9c; color: #fff; cursor: pointer; }
button:focus-visible { outline: 3px solid #f2b705; outline-offset: 2px; }
.note { border-left: 4px solid #0b4f9c; padding: .25rem .75rem; background: #f1f5fb; }
footer { margin-top: 2rem; font-size: .85rem; color: #4a4a4a; }
"""


def render_preview(view: ConfirmationView) -> tuple[int, str]:
    """The page the link opens (GET). Only the button confirms."""
    alert = view.alert
    if view.outcome is not None or alert is None:
        return _problem(view)
    message = alert.message
    body = [
        f"<p>Hola {escape(message.contact_name)}:</p>",
        "<p>Willay te avisó de este incidente. Confírmalo para que no se siga avisando al "
        "siguiente nivel.</p>",
        _summary(alert),
    ]
    button = "Confirmar que lo vi"
    if alert.incident_status is IncidentStatus.ACKNOWLEDGED:
        body.append(f'<p class="note">{_already_acknowledged(alert)}</p>')
        button = "Registrar que lo vi"
    body.append(f'<form method="post"><button type="submit">{button}</button></form>')
    return 200, _page("Confirma la alerta", body)


def render_result(view: ConfirmationView) -> tuple[int, str]:
    """The page after pressing the button (POST)."""
    alert = view.alert
    if view.outcome is ConfirmOutcome.CONFIRMED and alert is not None:
        return 200, _page(
            "¡Gracias! Confirmaste la alerta",
            [
                "<p>Quedó registrado que la viste. Willay no avisará al siguiente nivel.</p>",
                _summary(alert),
            ],
        )
    if view.outcome is ConfirmOutcome.ALREADY_ACKNOWLEDGED and alert is not None:
        return 200, _page(
            "Gracias: quedó registrado que la viste",
            [f'<p class="note">{_already_acknowledged(alert)}</p>', _summary(alert)],
        )
    return _problem(view)


def _problem(view: ConfirmationView) -> tuple[int, str]:
    alert = view.alert
    summary_html = [_summary(alert)] if alert is not None else []
    match view.outcome:
        case ConfirmOutcome.ALREADY_RESOLVED:
            return 200, _page(
                "Este incidente ya fue resuelto",
                ["<p>No hace falta confirmarlo.</p>", *summary_html],
            )
        case ConfirmOutcome.USED:
            return 410, _page(
                "Este enlace ya se usó",
                ["<p>La alerta ya fue confirmada con este enlace.</p>", *summary_html],
            )
        case ConfirmOutcome.EXPIRED:
            return 410, _page(
                "Este enlace venció",
                [
                    "<p>Los enlaces de confirmación valen 24 horas. Si el incidente sigue "
                    "abierto, comunícate con el equipo de operaciones.</p>",
                    *summary_html,
                ],
            )
        case _:
            return 404, _page(
                "Enlace no válido",
                ["<p>Revisa que copiaste el enlace completo desde el mensaje.</p>"],
            )


def _already_acknowledged(alert: AlertToConfirm) -> str:
    who = escape(alert.acknowledged_by) if alert.acknowledged_by else "Otra persona"
    when = (
        f" el {escape(local_time(alert.incident_acknowledged_at, alert.message.timezone))}"
        if alert.incident_acknowledged_at is not None
        else ""
    )
    return f"{who} ya lo había confirmado{when}."


def _summary(alert: AlertToConfirm) -> str:
    rows = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>"
        for label, value in summary(alert.message)
    )
    return f"<dl>{rows}</dl>"


def _page(title: str, body: list[str]) -> str:
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{escape(title)} · Willay</title><style>{_STYLE}</style></head>"
        f"<body><main><h1>{escape(title)}</h1>{''.join(body)}</main>"
        "<footer>Willay es una herramienta de apoyo para operadores: no reemplaza los avisos "
        "oficiales (INDECI, COER, SISMATE).</footer></body></html>"
    )
