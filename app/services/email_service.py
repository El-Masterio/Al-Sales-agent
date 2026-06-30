"""
app/services/email_service.py
=============================
Email sending abstraction across SendGrid, AWS SES, and SMTP.

Responsibilities:
  - Inject tracking pixel + rewrite links for open/click tracking
  - CSS-inline HTML for email-client compatibility (premailer)
  - Generate plain-text alternative from HTML
  - Build RFC-compliant Message-ID / threading headers
  - Send via the configured provider with a unified interface
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from email.utils import make_msgid

import html2text
import structlog
from premailer import transform

from app.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class SendResult:
    success: bool
    provider: str
    provider_message_id: str | None
    message_id: str
    error: str | None = None


@dataclass
class OutgoingEmail:
    to_email: str
    to_name: str | None
    from_email: str
    from_name: str
    subject: str
    body_html: str
    body_text: str
    reply_to: str | None = None
    tracking_id: uuid.UUID | None = None
    in_reply_to: str | None = None
    thread_references: str | None = None


# =============================================================================
# Tracking injection
# =============================================================================

class TrackingInjector:
    @staticmethod
    def inject_open_pixel(html: str, tracking_id: uuid.UUID) -> str:
        base = settings.email_tracking_base_url_str
        if not base:
            return html
        pixel_path = settings.EMAIL_OPEN_PIXEL_PATH.format(tracking_id=tracking_id)
        pixel = f'<img src="{base}{pixel_path}" width="1" height="1" alt="" style="display:none" />'
        if "</body>" in html:
            return html.replace("</body>", f"{pixel}</body>")
        return html + pixel

    @staticmethod
    def rewrite_links(html: str, tracking_id: uuid.UUID) -> str:
        import re
        from urllib.parse import quote

        base = settings.email_tracking_base_url_str
        if not base:
            return html
        click_path = settings.EMAIL_CLICK_REDIRECT_PATH.format(tracking_id=tracking_id)

        def _replace(match: re.Match) -> str:
            original_url = match.group(1)
            if original_url.startswith("mailto:") or original_url.startswith("#"):
                return match.group(0)
            tracked = f'{base}{click_path}?url={quote(original_url, safe="")}'
            return f'href="{tracked}"'

        return re.sub(r'href="([^"]+)"', _replace, html)


# =============================================================================
# Provider adapters
# =============================================================================

class BaseEmailProvider:
    name = "base"

    async def send(self, email: OutgoingEmail, message_id: str) -> SendResult:
        raise NotImplementedError


class SendGridProvider(BaseEmailProvider):
    name = "sendgrid"

    async def send(self, email: OutgoingEmail, message_id: str) -> SendResult:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Content,
            Email as SGEmail,
            Mail,
            To,
        )

        if not settings.SENDGRID_API_KEY:
            return SendResult(False, self.name, None, message_id, "SendGrid not configured")

        try:
            mail = Mail(
                from_email=SGEmail(email.from_email, email.from_name),
                to_emails=To(email.to_email, email.to_name),
                subject=email.subject,
            )
            mail.add_content(Content("text/plain", email.body_text))
            mail.add_content(Content("text/html", email.body_html))
            if email.reply_to:
                mail.reply_to = SGEmail(email.reply_to)

            # Custom headers for threading
            mail.header = [{"Message-ID": message_id}]
            if email.in_reply_to:
                mail.header.append({"In-Reply-To": email.in_reply_to})

            client = SendGridAPIClient(settings.SENDGRID_API_KEY)
            # SendGrid SDK is sync; run in a thread to avoid blocking the loop
            import asyncio

            response = await asyncio.to_thread(client.send, mail)

            provider_msg_id = response.headers.get("X-Message-Id") if response.headers else None
            success = 200 <= response.status_code < 300
            return SendResult(success, self.name, provider_msg_id, message_id)
        except Exception as exc:
            logger.error("sendgrid_send_failed", error=str(exc), to=email.to_email)
            return SendResult(False, self.name, None, message_id, str(exc))


class SESProvider(BaseEmailProvider):
    name = "ses"

    async def send(self, email: OutgoingEmail, message_id: str) -> SendResult:
        import asyncio

        import boto3

        if not (settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY):
            return SendResult(False, self.name, None, message_id, "SES not configured")

        try:
            def _send_sync() -> dict:
                client = boto3.client(
                    "ses",
                    region_name=settings.AWS_REGION,
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                )
                return client.send_email(
                    Source=f"{email.from_name} <{email.from_email}>",
                    Destination={"ToAddresses": [email.to_email]},
                    Message={
                        "Subject": {"Data": email.subject},
                        "Body": {
                            "Text": {"Data": email.body_text},
                            "Html": {"Data": email.body_html},
                        },
                    },
                    ConfigurationSetName=settings.SES_CONFIGURATION_SET,
                    ReplyToAddresses=[email.reply_to] if email.reply_to else [],
                )

            response = await asyncio.to_thread(_send_sync)
            return SendResult(True, self.name, response.get("MessageId"), message_id)
        except Exception as exc:
            logger.error("ses_send_failed", error=str(exc), to=email.to_email)
            return SendResult(False, self.name, None, message_id, str(exc))


class SMTPProvider(BaseEmailProvider):
    name = "smtp"

    async def send(self, email: OutgoingEmail, message_id: str) -> SendResult:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        if not (settings.SMTP_HOST and settings.SMTP_USERNAME):
            return SendResult(False, self.name, None, message_id, "SMTP not configured")

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = email.subject
            msg["From"] = f"{email.from_name} <{email.from_email}>"
            msg["To"] = f"{email.to_name} <{email.to_email}>" if email.to_name else email.to_email
            msg["Message-ID"] = message_id
            if email.reply_to:
                msg["Reply-To"] = email.reply_to
            if email.in_reply_to:
                msg["In-Reply-To"] = email.in_reply_to
            if email.thread_references:
                msg["References"] = email.thread_references

            msg.attach(MIMEText(email.body_text, "plain"))
            msg.attach(MIMEText(email.body_html, "html"))

            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                use_tls=settings.SMTP_USE_SSL,
                start_tls=settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL,
            )
            return SendResult(True, self.name, None, message_id)
        except Exception as exc:
            logger.error("smtp_send_failed", error=str(exc), to=email.to_email)
            return SendResult(False, self.name, None, message_id, str(exc))


# =============================================================================
# Email service facade
# =============================================================================

class EmailService:
    _providers: dict[str, BaseEmailProvider] = {
        "sendgrid": SendGridProvider(),
        "ses": SESProvider(),
        "smtp": SMTPProvider(),
    }

    def prepare_email(
        self,
        *,
        to_email: str,
        to_name: str | None,
        from_email: str,
        from_name: str,
        subject: str,
        body_html: str,
        body_text: str,
        tracking_id: uuid.UUID,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
    ) -> tuple[OutgoingEmail, str]:
        """
        Apply tracking, CSS inlining, and generate the Message-ID.
        Returns (OutgoingEmail, message_id).
        """
        # Inject tracking
        tracked_html = TrackingInjector.rewrite_links(body_html, tracking_id)
        tracked_html = TrackingInjector.inject_open_pixel(tracked_html, tracking_id)

        # CSS inline for email client compatibility
        try:
            inlined_html = transform(tracked_html)
        except Exception:
            inlined_html = tracked_html

        # Ensure a plain-text alternative exists
        if not body_text.strip():
            h = html2text.HTML2Text()
            h.ignore_links = False
            body_text = h.handle(body_html)

        domain = from_email.split("@")[-1]
        message_id = make_msgid(domain=domain)

        outgoing = OutgoingEmail(
            to_email=to_email,
            to_name=to_name,
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            body_html=inlined_html,
            body_text=body_text,
            reply_to=reply_to,
            tracking_id=tracking_id,
            in_reply_to=in_reply_to,
        )
        return outgoing, message_id

    async def send(self, email: OutgoingEmail, message_id: str, provider: str | None = None) -> SendResult:
        provider_name = provider or settings.DEFAULT_EMAIL_PROVIDER
        adapter = self._providers.get(provider_name)
        if adapter is None:
            return SendResult(False, provider_name, None, message_id, f"Unknown provider: {provider_name}")
        return await adapter.send(email, message_id)


email_service = EmailService()
