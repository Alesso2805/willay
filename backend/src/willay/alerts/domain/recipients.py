"""What the dashboard may show about an alert's recipient (VIG-26, SPEC: privacy).

The email is personal data: only users who may see contact details (operator and admin) get
it. A Telegram `chat_id` never leaves the API, whoever asks: knowing whether the contact has
Telegram linked is enough to operate.
"""

from willay.alerts.domain.alerts import Channel


def shown_email(channel: Channel, destination: str | None, may_see_details: bool) -> str | None:
    """The alert's email address, if this user may see it; otherwise None."""
    if channel is not Channel.EMAIL or not may_see_details:
        return None
    return destination
