from __future__ import annotations

import mimetypes
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional, Sequence

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.audit import AuditService
from app.services.storage import resolve_storage_root
from twilio.base.exceptions import TwilioException
from twilio.rest import Client


@dataclass
class EmailConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    starttls: bool


@dataclass
class SMSConfig:
    account_sid: str
    auth_token: str
    from_number: str | None
    messaging_service_sid: str | None


@dataclass
class EmailAttachment:
    filename: str
    content: bytes
    mime_type: str = "application/pdf"


class NotificationService:
    def __init__(
        self,
        audit_service: Optional[AuditService] = None,
        email_config: Optional[EmailConfig] = None,
        public_base_url: str | None = None,
        agent_download_url: str | None = None,
        sms_config: Optional[SMSConfig] = None,
        template_root: Path | None = None,
    ) -> None:
        self.audit_service = audit_service
        self.email_config = email_config
        self.public_base_url = public_base_url
        self.agent_download_url = agent_download_url
        self.sms_config = sms_config
        self.template_root = template_root or Path(__file__).resolve().parent.parent / "templates"
        self.template_env = Environment(
            loader=FileSystemLoader(self.template_root),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def configure_public_base_url(self, base_url: str | None) -> None:
        self.public_base_url = base_url

    def configure_agent_download_url(self, url: str | None) -> None:
        self.agent_download_url = url

    def configure_email(
        self,
        host: str,
        port: int,
        sender: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
    ) -> None:
        self.email_config = EmailConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            sender=sender,
            starttls=starttls,
        )

    def configure_sms(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str | None = None,
        messaging_service_sid: str | None = None,
    ) -> None:
        self.sms_config = SMSConfig(
            account_sid=account_sid,
            auth_token=auth_token,
            from_number=from_number,
            messaging_service_sid=messaging_service_sid,
        )

    def _record_event(
        self,
        *,
        event_type: str,
        document,
        channel: str,
        request=None,
        party=None,
        extra: dict | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        if not self.audit_service:
            return
        details: dict[str, object | None] = {
            "request_id": str(request.id) if request else None,
            "party_email": getattr(party, "email", None) if party else None,
            "channel": channel,
        }
        if extra:
            details.update(extra)
        self.audit_service.record_event(
            event_type=event_type,
            actor_id=None,
            actor_role=None,
            document_id=document.id if document else None,
            details=details,
        )

    def _build_action_link(self, token: str | None) -> str | None:
        if not token or not self.public_base_url:
            return None
        base = self.public_base_url.rstrip("/")
        return f"{base}/public/sign/{token}"

    def _render_template(self, template_name: str, context: dict) -> str:
        template = self.template_env.get_template(template_name)
        return template.render(**context)

    def _signature_plain_text(  # type: ignore[no-untyped-def]
        self,
        *,
        party,
        document,
        action_link: str | None,
        deadline_display: str | None = None,
        document_status: str | None = None,
        agent_download_url: str | None = None,
    ) -> str:
        lines = [
            f"Ol? {party.full_name},",
            "",
            f"Voc? tem uma nova solicita??o de assinatura para '{document.name}'.",
        ]
        if document_status:
            lines.append(f"Status atual: {document_status}.")
        if deadline_display:
            lines.append(f"Prazo: {deadline_display}.")
        if action_link:
            lines.extend(["", "Assinar agora:", action_link])
        else:
            lines.extend(["", "Entre em contato com o solicitante para obter o link de assinatura."])
        if agent_download_url:
            lines.extend(
                [
                    "",
                    "Precisa instalar o agente de assinatura neste computador?",
                    agent_download_url,
                ]
            )
        lines.extend(["", "Equipe NacionalSign"])
        return "\n".join(lines)



    def _send_sms(
        self,
        *,
        party,
        document,
        action_link: str | None,
        deadline_display: str | None = None,
        document_status: str | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        if not self.sms_config:
            raise RuntimeError("SMS sender not configured")
        client = Client(self.sms_config.account_sid, self.sms_config.auth_token)
        parts = [f"Voc? tem uma solicita??o para '{document.name}'."]
        if document_status:
            parts.append(f"Status: {document_status}.")
        if deadline_display:
            parts.append(f"Prazo: {deadline_display}.")
        if action_link:
            parts.append(f"Assinar agora: {action_link}")
        else:
            parts.append("Entre em contato com o solicitante para o link.")
        body = " ".join(parts)
        message_kwargs = {"to": party.phone_number, "body": body}
        if self.sms_config.messaging_service_sid:
            message_kwargs["messaging_service_sid"] = self.sms_config.messaging_service_sid
        elif self.sms_config.from_number:
            message_kwargs["from_"] = self.sms_config.from_number
        else:
            raise RuntimeError("SMS sender not configured")

        client.messages.create(**message_kwargs)

    def notify_signature_request(
        self,
        request,
        party,
        document,
        token: str | None = None,
        step=None,
    ) -> bool:  # type: ignore[no-untyped-def]
        channel = (getattr(party, "notification_channel", None) or "email").lower()
        deadline_at = getattr(step, "deadline_at", None)
        if deadline_at is None:
            deadline_at = getattr(request, "token_expires_at", None)
        deadline_display: str | None = None
        deadline_iso: str | None = None
        if isinstance(deadline_at, datetime):
            deadline_display = deadline_at.strftime("%d/%m/%Y %H:%M")
            deadline_iso = deadline_at.isoformat()

        self._record_event(
            event_type="notification_attempt",
            request=request,
            party=party,
            document=document,
            channel=channel,
            extra={"deadline_at": deadline_iso} if deadline_iso else None,
        )

        if channel not in {"email", "sms"}:
            self._record_event(
                event_type="notification_skipped",
                request=request,
                party=party,
                document=document,
                channel=channel,
                extra={"reason": "unsupported_channel"},
            )
            return False

        action_link = self._build_action_link(token)
        download_url: str | None = None
        if isinstance(self.agent_download_url, str):
            stripped = self.agent_download_url.strip()
            download_url = stripped or None

        status_value = getattr(document, "status", None)
        if hasattr(status_value, "value"):
            status_value = status_value.value
        status_display = status_value.replace("_", " ") if isinstance(status_value, str) else None

        if channel == "sms":
            if not self.sms_config:
                self._record_event(
                    event_type="notification_skipped",
                    request=request,
                    party=party,
                    document=document,
                    channel=channel,
                    extra={"reason": "sms_config_missing"},
                )
                return False
            if not getattr(party, "phone_number", None):
                self._record_event(
                    event_type="notification_skipped",
                    request=request,
                    party=party,
                    document=document,
                    channel=channel,
                    extra={"reason": "missing_phone"},
                )
                return False

            try:
                self._send_sms(
                    party=party,
                    document=document,
                    action_link=action_link,
                    deadline_display=deadline_display,
                    document_status=status_display,
                )
            except (RuntimeError, ValueError) as exc:
                self._record_event(
                    event_type="notification_skipped",
                    request=request,
                    party=party,
                    document=document,
                    channel=channel,
                    extra={"reason": str(exc)},
                )
                return False
            except TwilioException as exc:  # pragma: no cover - third-party failure
                self._record_event(
                    event_type="notification_error",
                    request=request,
                    party=party,
                    document=document,
                    channel=channel,
                    extra={"reason": str(exc)},
                )
                return False

            self._record_event(
                event_type="notification_sent",
                request=request,
                party=party,
                document=document,
                channel=channel,
                extra={"action_link": action_link, "deadline_at": deadline_iso} if action_link else {"deadline_at": deadline_iso},
            )
            return True

        if not self.email_config:
            self._record_event(
                event_type="notification_skipped",
                request=request,
                party=party,
                document=document,
                channel=channel,
                extra={"reason": "email_config_missing"},
            )
            return False
        if not getattr(party, "email", None):
            self._record_event(
                event_type="notification_skipped",
                request=request,
                party=party,
                document=document,
                channel=channel,
                extra={"reason": "missing_email"},
            )
            return False

        html_body = self._render_template(
            "email/signature_request.html",
            {
                "signer_name": party.full_name,
                "document_name": document.name,
                "document_status": status_display or status_value,
                "action_link": action_link,
                "deadline_display": deadline_display,
                "deadline_iso": deadline_iso,
                "agent_download_url": download_url,
            },
        )
        text_body = self._signature_plain_text(
            party=party,
            document=document,
            action_link=action_link,
            deadline_display=deadline_display,
            document_status=status_display,
            agent_download_url=download_url,
        )

        try:
            self._send_email(
                to=party.email,
                subject=f"Assinatura pendente: {document.name}",
                html_body=html_body,
                text_body=text_body,
            )
        except Exception as exc:  # pragma: no cover - best effort logging
            self._record_event(
                event_type="notification_error",
                request=request,
                party=party,
                document=document,
                channel=channel,
                extra={"reason": str(exc), "action_link": action_link},
            )
            return False

        self._record_event(
            event_type="notification_sent",
            request=request,
            party=party,
            document=document,
            channel=channel,
            extra={"action_link": action_link, "deadline_at": deadline_iso} if action_link else {"deadline_at": deadline_iso},
        )
        return True




    def notify_workflow_completed(
        self,
        *,
        document,
        parties: Iterable,
        attachments: Sequence[str | Path] | None = None,
        extra_recipients: Sequence[str] | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        if not self.email_config:
            return

        recipients = []
        for party in parties:
            email = getattr(party, "email", None)
            if email:
                recipients.append(email)
        for email in extra_recipients or []:
            recipients.append(email)

        unique_emails = []
        seen = set()
        for email in recipients:
            normalized = email.lower()
            if normalized not in seen:
                seen.add(normalized)
                unique_emails.append(email)

        if not unique_emails:
            return

        storage_root = resolve_storage_root()
        attachment_objects: list[EmailAttachment] = []
        for item in attachments or []:
            path = Path(item)
            if not path.is_absolute():
                path = (storage_root / path).resolve()
            if not path.exists():
                continue
            mime_type, _ = mimetypes.guess_type(path.name)
            attachment_objects.append(
                EmailAttachment(
                    filename=path.name,
                    content=path.read_bytes(),
                    mime_type=mime_type or "application/octet-stream",
                )
            )

        html_body = self._render_template(
            "email/workflow_completed.html",
            {
                "document_name": document.name,
                "document_id": document.id,
                "has_attachments": bool(attachment_objects),
            },
        )
        text_body = (
            f"Documento '{document.name}' foi finalizado.\n"
            "Os anexos desta mensagem contêm o relatório de auditoria gerado pela NacionalSign."
        )

        for email in unique_emails:
            try:
                self._send_email(
                    to=email,
                    subject=f"Documento finalizado: {document.name}",
                    html_body=html_body,
                    text_body=text_body,
                    attachments=attachment_objects,
                )
            except Exception as exc:  # pragma: no cover
                self._record_event(
                    event_type="workflow_completed_notification_error",
                    document=document,
                    channel="email",
                    extra={"recipient": email, "reason": str(exc)},
                )
                continue

            self._record_event(
                event_type="workflow_completed_notification_sent",
                document=document,
                channel="email",
                extra={"recipient": email},
            )

    def send_user_credentials_email(
        self,
        *,
        to: str,
        full_name: str,
        username: str,
        temporary_password: str,
        subject: str | None = None,
    ) -> None:
        if not self.email_config:
            raise RuntimeError("Email sender not configured")

        safe_subject = subject or "Acesso ao sistema NacionalSign"
        html_body = (
            f"<p>Olá {full_name},</p>"
            "<p>Segue abaixo o seu acesso ao sistema NacionalSign:</p>"
            f"<p><strong>Usuário:</strong> {username}<br/>"
            f"<strong>Senha temporária:</strong> {temporary_password}</p>"
            "<p>No primeiro acesso você deverá alterar a senha.</p>"
            "<p>Se você não reconhece esta solicitação, entre em contato com o suporte.</p>"
        )
        text_body = (
            f"Olá {full_name},\n\n"
            "Segue abaixo o seu acesso ao sistema NacionalSign:\n"
            f"Usuário: {username}\n"
            f"Senha temporária: {temporary_password}\n\n"
            "No primeiro acesso você deverá alterar a senha.\n"
            "Se você não reconhece esta solicitação, entre em contato com o suporte.\n"
        )

        self._send_email(
            to=to,
            subject=safe_subject,
            html_body=html_body,
            text_body=text_body,
        )
        self._record_event(
            event_type="user_credentials_email_sent",
            document=None,
            channel="email",
            extra={"recipient": to},
        )

    def _send_email(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
        attachments: Sequence[EmailAttachment] | None = None,
    ) -> None:
        if not self.email_config:
            raise RuntimeError("Email sender not configured")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.email_config.sender
        message["To"] = to

        plain_body = text_body or ""
        message.set_content(plain_body, subtype="plain", charset="utf-8")
        message.add_alternative(html_body, subtype="html", charset="utf-8")

        for attachment in attachments or []:
            maintype = "application"
            subtype = "octet-stream"
            if attachment.mime_type and "/" in attachment.mime_type:
                maintype, subtype = attachment.mime_type.split("/", 1)
            message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )

        with smtplib.SMTP(self.email_config.host, self.email_config.port, timeout=30) as smtp:
            if self.email_config.starttls:
                smtp.starttls()
            if self.email_config.username and self.email_config.password:
                smtp.login(self.email_config.username, self.email_config.password)
            smtp.send_message(message)
