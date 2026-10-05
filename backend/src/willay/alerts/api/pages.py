"""Alert confirmation pages (VIG-23): plain HTML, no JavaScript.

Opened from email, sometimes on a modest phone: a light page that works without scripts
and is accessible (state is stated in text, never by color alone). All variable data is
escaped. Written in the contact's language (VIG-40); a link that matches no alert has no
contact, so it follows the browser's.
"""

from html import escape

from willay.alerts.application.confirmation import AlertToConfirm, ConfirmationView
from willay.alerts.domain.confirmation import ConfirmOutcome
from willay.alerts.domain.email import local_time, summary
from willay.incidents.domain.lifecycle import IncidentStatus
from willay.shared.i18n import negotiate, translate
from willay.shared.languages import Language

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
:root { color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  body { color: #e8eef5; background: #0f2132; }
  button { background: #5fd4e8; color: #0b1d2e; }
  .note { border-left-color: #5fd4e8; background: #15293e; }
  footer { color: #b2c1d1; }
}
"""
# Dark mode (VIG-41) follows the device, the only signal a page without login has. As in the
# dashboard, every pair keeps ≥ 4.5:1 (text 14:1, button 9.8:1, footer 8.9:1).


def page_language(view: ConfirmationView, accept_language: str | None) -> Language:
    """The contact's language, or the browser's when the link matches no alert."""
    return view.alert.message.language if view.alert is not None else negotiate(accept_language)


def render_preview(view: ConfirmationView, language: Language) -> tuple[int, str]:
    """The page the link opens (GET). Only the button confirms."""
    alert = view.alert
    if view.outcome is not None or alert is None:
        return _problem(view, language)
    body = [
        f"<p>{_text('greeting', language, name=alert.message.contact_name)}</p>",
        f"<p>{_text('intro', language)}</p>",
        _summary(alert),
    ]
    button = _text("confirm", language)
    if alert.incident_status is IncidentStatus.ACKNOWLEDGED:
        body.append(f'<p class="note">{_already_acknowledged(alert, language)}</p>')
        button = _text("record_seen", language)
    body.append(f'<form method="post"><button type="submit">{button}</button></form>')
    return 200, _page(_text("title", language), body, language)


def render_result(view: ConfirmationView, language: Language) -> tuple[int, str]:
    """The page after pressing the button (POST)."""
    alert = view.alert
    if view.outcome is ConfirmOutcome.CONFIRMED and alert is not None:
        body = [f"<p>{_text('confirmed', language)}</p>", _summary(alert)]
        return 200, _page(_text("confirmed_title", language), body, language)
    if view.outcome is ConfirmOutcome.ALREADY_ACKNOWLEDGED and alert is not None:
        body = [f'<p class="note">{_already_acknowledged(alert, language)}</p>', _summary(alert)]
        return 200, _page(_text("seen_title", language), body, language)
    return _problem(view, language)


def _problem(view: ConfirmationView, language: Language) -> tuple[int, str]:
    summary_html = [_summary(view.alert)] if view.alert is not None else []
    match view.outcome:
        case ConfirmOutcome.ALREADY_RESOLVED:
            status, name = 200, "resolved"
        case ConfirmOutcome.USED:
            status, name = 410, "used"
        case ConfirmOutcome.EXPIRED:
            status, name = 410, "expired"
        case _:
            # Nothing about the incident: the link is not valid.
            status, name, summary_html = 404, "invalid", []
    body = [f"<p>{_text(name, language)}</p>", *summary_html]
    return status, _page(_text(f"{name}_title", language), body, language)


def _already_acknowledged(alert: AlertToConfirm, language: Language) -> str:
    who = alert.acknowledged_by or translate("alerts.page.someone_else", language)
    if alert.incident_acknowledged_at is None:
        return _text("already_acknowledged", language, who=who)
    time = local_time(alert.incident_acknowledged_at, alert.message.timezone, language)
    return _text("already_acknowledged_at", language, who=who, time=time)


def _summary(alert: AlertToConfirm) -> str:
    rows = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>"
        for label, value in summary(alert.message)
    )
    return f"<dl>{rows}</dl>"


def _text(key: str, language: Language, **params: str) -> str:
    """A page text as HTML: the parameters (names, times) are escaped, and so is the text,
    so a translation can never inject markup either."""
    return escape(translate(f"alerts.page.{key}", language, **params))


def _page(title: str, body: list[str], language: Language) -> str:
    # `title` is already escaped by _text.
    return (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{title} · Willay</title><style>{_STYLE}</style></head>"
        f"<body><main><h1>{title}</h1>{''.join(body)}</main>"
        f"<footer>{_text('disclaimer', language)}</footer></body></html>"
    )
