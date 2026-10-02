"""VIG-26: what the dashboard may show about an alert's recipient."""

from willay.alerts.domain.alerts import Channel
from willay.alerts.domain.recipients import shown_email


def test_the_email_only_reaches_users_who_may_see_contact_details() -> None:
    assert shown_email(Channel.EMAIL, "rosa@rimac.test", may_see_details=True) == "rosa@rimac.test"
    assert shown_email(Channel.EMAIL, "rosa@rimac.test", may_see_details=False) is None


def test_a_telegram_chat_never_leaves_the_api() -> None:
    assert shown_email(Channel.TELEGRAM, "123456789", may_see_details=True) is None
    assert shown_email(Channel.TELEGRAM, "123456789", may_see_details=False) is None


def test_a_skipped_alert_has_nothing_to_show() -> None:
    assert shown_email(Channel.EMAIL, None, may_see_details=True) is None
