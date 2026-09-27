import asyncio
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any

from app.core.config import get_settings
from app.schemas.email import EmailProviderName, EmailProviderStatus, EmailSendRequest, EmailSendResult


class EmailProvider(ABC):
    name: EmailProviderName

    @abstractmethod
    def availability(self) -> EmailProviderStatus:
        raise NotImplementedError

    @abstractmethod
    async def send(self, request: EmailSendRequest) -> EmailSendResult:
        raise NotImplementedError


class DryRunEmailProvider(EmailProvider):
    name: EmailProviderName = "dry_run"

    def availability(self) -> EmailProviderStatus:
        return EmailProviderStatus(
            provider=self.name,
            available=True,
            status="available",
            metadata={"external_send": False},
        )

    async def send(self, request: EmailSendRequest) -> EmailSendResult:
        return EmailSendResult(
            status="sent",
            provider=self.name,
            to_email=request.to_email,
            subject=request.subject,
            provider_message_id=f"dry-run:{request.idempotency_key or request.to_email}",
            dry_run=True,
            metadata={"external_send": False},
        )


class SmtpEmailProvider(EmailProvider):
    def __init__(
        self,
        *,
        name: EmailProviderName,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        use_ssl: bool,
        use_starttls: bool,
        required_env: list[str],
    ) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        self.use_ssl = use_ssl
        self.use_starttls = use_starttls
        self.required_env = required_env

    def availability(self) -> EmailProviderStatus:
        missing = []
        if not self.host:
            missing.append(f"{self.name.upper()}_SMTP_HOST")
        if not self.username:
            missing.append(f"{self.name.upper()}_SMTP_USERNAME")
        if not self.password:
            missing.append(f"{self.name.upper()}_SMTP_PASSWORD")
        if not (self.from_email or self.username):
            missing.append(f"{self.name.upper()}_SMTP_FROM_EMAIL")
        return EmailProviderStatus(
            provider=self.name,
            available=not missing,
            status="available" if not missing else "unavailable",
            required_env=self.required_env,
            missing_env=missing,
            recoverable_error="Missing SMTP provider configuration." if missing else None,
            metadata={
                "host": self.host,
                "port": self.port,
                "use_ssl": self.use_ssl,
                "use_starttls": self.use_starttls,
            },
        )

    async def send(self, request: EmailSendRequest) -> EmailSendResult:
        status = self.availability()
        if not status.available:
            return EmailSendResult(
                status="failed",
                provider=self.name,
                to_email=request.to_email,
                subject=request.subject,
                error=status.recoverable_error,
                metadata=status.model_dump(mode="json"),
            )
        try:
            message = _build_message(request, self.from_email or self.username, self.from_name)
            await asyncio.to_thread(self._send_sync, message)
        except Exception as exc:
            return EmailSendResult(
                status="failed",
                provider=self.name,
                to_email=request.to_email,
                subject=request.subject,
                error=f"{type(exc).__name__}: {exc}",
            )
        return EmailSendResult(
            status="sent",
            provider=self.name,
            to_email=request.to_email,
            subject=request.subject,
            provider_message_id=f"smtp:{self.name}:{request.idempotency_key or request.to_email}",
        )

    def _send_sync(self, message: EmailMessage) -> None:
        if self.use_ssl:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=20) as smtp:
                smtp.login(self.username, self.password)
                smtp.send_message(message)
            return
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            if self.use_starttls:
                smtp.starttls()
            smtp.login(self.username, self.password)
            smtp.send_message(message)


def build_email_providers() -> dict[EmailProviderName, EmailProvider]:
    settings = get_settings()
    return {
        "dry_run": DryRunEmailProvider(),
        "qq": SmtpEmailProvider(
            name="qq",
            host=settings.qq_smtp_host,
            port=settings.qq_smtp_port,
            username=settings.qq_smtp_username,
            password=settings.qq_smtp_password,
            from_email=settings.qq_smtp_from_email or settings.qq_smtp_username,
            from_name=settings.qq_smtp_from_name,
            use_ssl=True,
            use_starttls=False,
            required_env=["QQ_SMTP_USERNAME", "QQ_SMTP_PASSWORD"],
        ),
        "outlook": SmtpEmailProvider(
            name="outlook",
            host=settings.outlook_smtp_host,
            port=settings.outlook_smtp_port,
            username=settings.outlook_smtp_username,
            password=settings.outlook_smtp_password,
            from_email=settings.outlook_smtp_from_email or settings.outlook_smtp_username,
            from_name=settings.outlook_smtp_from_name,
            use_ssl=False,
            use_starttls=True,
            required_env=["OUTLOOK_SMTP_USERNAME", "OUTLOOK_SMTP_PASSWORD"],
        ),
    }


def _build_message(request: EmailSendRequest, default_from_email: str, default_from_name: str) -> EmailMessage:
    message = EmailMessage()
    from_email = request.from_email or default_from_email
    from_name = request.from_name or default_from_name
    message["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    message["To"] = request.to_email
    message["Subject"] = request.subject
    if request.reply_to:
        message["Reply-To"] = request.reply_to
    message.set_content(request.body)
    return message
