import logging
from abc import ABC, abstractmethod

log = logging.getLogger("healthtrace.email")


class EmailService(ABC):
    """Later providers: SMTP, SendGrid, AWS SES."""

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None: ...


class DevelopmentEmailService(EmailService):
    """Never sends mail. Logs only the recipient and subject (message bodies can carry one-time links)."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.info("dev email queued (not sent): to=%s subject=%s", to, subject)


def get_email_service() -> EmailService:
    return DevelopmentEmailService()
