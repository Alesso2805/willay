"""EmailSender por SMTP (aiosmtplib). En local, el servidor es Mailpit."""

from email.message import EmailMessage

import aiosmtplib

from vigia.alerts.application.dispatch import DeliveryError
from vigia.alerts.domain.email import EmailContent


class SmtpEmailSender:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        *,
        timeout_s: float = 10.0,
        start_tls: bool = False,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._host, self._port, self._sender = host, port, sender
        self._timeout_s, self._start_tls = timeout_s, start_tls
        self._username, self._password = username, password

    async def send(self, to: str, content: EmailContent) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = content.subject
        message.set_content(content.body)
        try:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                timeout=self._timeout_s,
                start_tls=self._start_tls,
                username=self._username,
                password=self._password,
            )
        except aiosmtplib.SMTPResponseException as exc:
            # Solo el código y el tipo: el mensaje del servidor suele repetir el destinatario.
            raise DeliveryError(f"{type(exc).__name__} {exc.code}") from exc
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise DeliveryError(type(exc).__name__) from exc
