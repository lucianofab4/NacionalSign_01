from __future__ import annotations
import base64
import mimetypes
import smtplib
import logging
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Iterable, Optional, Sequence
from uuid import UUID

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlmodel import Session, select
from twilio.base.exceptions import TwilioException
from twilio.rest import Client

from app.models.customer import Customer
from app.services.audit import AuditService
from app.services.storage import resolve_storage_root

@dataclass
class EmailConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    starttls: bool = True

@dataclass
class SendGridConfig:
    api_key: str
    sender: str | None

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

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(
        self,
        audit_service: Optional[AuditService] = None,
        email_config: Optional[EmailConfig] = None,
        public_base_url: str | None = None,
        agent_download_url: str | None = None,
        sms_config: Optional[SMSConfig] = None,
        template_root: Path | None = None,
        sendgrid_config: Optional[SendGridConfig] = None,
        email_backend: str = "smtp",
        session: Session | None = None,
    ) -> None:
        self.audit_service = audit_service
        self.email_config = email_config
        self.sendgrid_config = sendgrid_config
        normalized_backend = (email_backend or "smtp").strip().lower()
        self.email_backend = normalized_backend if normalized_backend in {"smtp", "sendgrid"} else "smtp"
        if self.sendgrid_config and self.email_backend != "sendgrid":
            self.email_backend = "sendgrid"
        self.public_base_url = public_base_url
        self.agent_download_url = agent_download_url
        self.sms_config = sms_config
        self.template_root = template_root or Path(__file__).resolve().parent.parent / "templates"
        self.template_env = Environment(
            loader=FileSystemLoader(self.template_root),
            autoescape=select_autoescape(["html", "xml"]),
        )
        if session is None:
            raise ValueError("NotificationService requer uma sessão de banco de dados para resolver clientes.")
        self.session = session

    def configure_public_base_url(self, base_url: str | None) -> None:
        self.public_base_url = base_url

    def configure_agent_download_url(self, url: str | None) -> None:
        self.agent_download_url = url

    def apply_email_settings(self, settings) -> None:
        preferred = (getattr(settings, "email_backend", "smtp") or "smtp").strip().lower()
        sender = getattr(settings, "smtp_sender", None)
        sendgrid_key = getattr(settings, "sendgrid_api_key", None)
        smtp_host = getattr(settings, "smtp_host", None)
        smtp_port = getattr(settings, "smtp_port", None)
        smtp_username = getattr(settings, "smtp_username", None)
        smtp_password = getattr(settings, "smtp_password", None)
        smtp_starttls = getattr(settings, "smtp_starttls", True)

        def use_sendgrid() -> bool:
            if sendgrid_key and sender:
                self.configure_sendgrid(api_key=sendgrid_key, sender=sender)
                return True
            return False

        def use_smtp() -> bool:
            if smtp_host and sender and smtp_port:
                self.configure_email(
                    host=smtp_host,
                    port=int(smtp_port),
                    sender=sender,
                    username=smtp_username,
                    password=smtp_password,
                    starttls=bool(smtp_starttls),
                )
                return True
            return False

        if preferred == "sendgrid":
            if use_sendgrid():
                return
            use_smtp()
            return
        if preferred == "smtp":
            if use_smtp():
                return
            use_sendgrid()
            return
        if not use_sendgrid():
            use_smtp()

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
        self.email_backend = "smtp"

    def configure_sendgrid(
        self,
        *,
        api_key: str,
        sender: str | None = None,
    ) -> None:
        self.sendgrid_config = SendGridConfig(api_key=api_key, sender=sender)
        self.email_backend = "sendgrid"

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
    ) -> None:
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

    def _email_sender_available(self) -> bool:
        if self.email_backend == "sendgrid":
            return self.sendgrid_config is not None
        return self.email_config is not None

    def _resolve_customer_display_name(self, tenant_id: UUID | None) -> str | None:
        """Returns the trade name registered for the tenant, if available."""
        if not tenant_id or not self.session:
            return None
        try:
            tenant_uuid = UUID(str(tenant_id))
        except (TypeError, ValueError):
            return None
        customer = self.session.exec(
            select(Customer).where(Customer.tenant_id == tenant_uuid)
        ).first()
        if customer:
            return customer.trade_name or customer.corporate_name
        return None

    def _build_action_link(self, token: str | None) -> str | None:
        if not token or not self.public_base_url:
            return None
        base = self.public_base_url.rstrip("/")
        return f"{base}/public/sign/{token}"

    def _render_template(self, template_name: str, context: dict) -> str:
        template = self.template_env.get_template(template_name)
        return template.render(**context)

    def _signature_plain_text(
        self,
        *,
        party,
        document,
        action_link: str | None,
        deadline_display: str | None = None,
        document_status: str | None = None,
        agent_download_url: str | None = None,
        group_info: dict | None = None,
        group_documents: list[dict] | None = None,
        company_name: str | None = None,
    ) -> str:
        lines = [
            f"Ola {party.full_name},",
            "",
            f"Voce tem uma nova solicitacao de assinatura para '{document.name}'.",
        ]
        if company_name:
            lines.append(f"Solicitante: {company_name}.")
        if document_status:
            lines.append(f"Status atual: {document_status}.")
        if deadline_display:
            lines.append(f"Prazo: {deadline_display}.")
        if group_info:
            title = group_info.get("title") or "lote de documentos"
            lines.append("")
            lines.append(f"Fluxo aplicado ao grupo: {title}.")
        if group_documents:
            lines.append("")
            lines.append("Documentos deste fluxo:")
            for item in group_documents:
                status = item.get("status")
                if status:
                    lines.append(f"- {item.get('name')} ({status})")
                else:
                    lines.append(f"- {item.get('name')}")
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
    ) -> None:
        if not self.sms_config:
            raise RuntimeError("SMS sender not configured")
        client = Client(self.sms_config.account_sid, self.sms_config.auth_token)
        parts = [f"Voce tem uma solicitacao para '{document.name}'."]
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

    def _get_document_pdf_attachment(self, document) -> EmailAttachment | None:
        storage_root = resolve_storage_root()
        version = getattr(document, "current_version", None) or getattr(document, "latest_version", None)
        if not version:
            return None
        path_str = version.storage_path or version.preview_url
        if not path_str:
            return None
        path = Path(path_str)
        if not path.is_absolute():
            path = (storage_root / path).resolve()
        if not path.exists():
            return None
        mime_type, _ = mimetypes.guess_type(path.name)
        return EmailAttachment(
            filename=path.name,
            content=path.read_bytes(),
            mime_type=mime_type or "application/pdf",
        )

    def notify_signature_request(
        self,
        request,
        party,
        document,
        token: str | None = None,
        step=None,
        *,
        group=None,
        group_documents: Sequence | None = None,
        requester_name: str | None = None,
    ) -> bool:
        channel = (getattr(party, "notification_channel", None) or "email").lower()
        deadline_at = getattr(step, "deadline_at", None)
        if deadline_at is None:
            deadline_at = getattr(request, "token_expires_at", None)
        deadline_display: str | None = None
        deadline_iso: str | None = None
        if isinstance(deadline_at, datetime):
            deadline_display = deadline_at.strftime("%d/%m/%Y %H:%M")
            deadline_iso = deadline_at.isoformat()
        normalized_group_docs = None
        if group_documents:
            normalized_group_docs = []
            for doc in group_documents:
                status_value = getattr(doc, "status", None)
                if hasattr(status_value, "value"):
                    status_value = status_value.value
                if isinstance(status_value, str):
                    status_display = status_value.replace("_", " ")
                else:
                    status_display = status_value
                normalized_group_docs.append({"name": getattr(doc, "name", ""), "status": status_display})
        group_context = None
        if group:
            group_context = {"title": getattr(group, "title", None)}
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
            except TwilioException as exc:
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
        if not self._email_sender_available():
            self._record_event(
                event_type="notification_skipped",
                request=request,
                party=party,
                document=document,
                channel=channel,
                extra={"reason": "email_sender_missing"},
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
        tenant_name = requester_name
        if not tenant_name and document is not None:
            customer_obj = getattr(document, "customer", None)
            if customer_obj:
                tenant_name = getattr(customer_obj, "trade_name", None) or getattr(customer_obj, "corporate_name", None)
        if not tenant_name:
            logger.warning(
                "Customer não encontrado para document_id=%s. Usando fallback.",
                getattr(document, "id", None),
            )
            tenant_name = "Empresa solicitante"

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
                "group_documents": normalized_group_docs,
                "group_title": group_context.get("title") if group_context else None,
                "requester_name": tenant_name,
            },
        )
        text_body = self._signature_plain_text(
            party=party,
            document=document,
            action_link=action_link,
            deadline_display=deadline_display,
            document_status=status_display,
            agent_download_url=download_url,
            group_info=group_context,
            group_documents=normalized_group_docs,
            company_name=tenant_name,
        )
        # Anexa PDF correto do documento atual
        attachment = self._get_document_pdf_attachment(document)
        attachments = [attachment] if attachment else None
        try:
            self._send_email(
                to=party.email,
                subject=f"Assinatura pendente: {document.name}",
                html_body=html_body,
                text_body=text_body,
                attachments=attachments,
            )
        except Exception as exc:
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
    ) -> None:
        if not self._email_sender_available():
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
            "Os anexos desta mensagem contem o relatorio de auditoria gerado pela NacionalSign."
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
            except Exception as exc:
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
        if not self._email_sender_available():
            raise RuntimeError("Email sender not configured")
        safe_subject = subject or "Acesso ao sistema NacionalSign"
        html_body = (
            f"<p>Ola {full_name},</p>"
            "<p>Segue abaixo o seu acesso ao sistema NacionalSign:</p>"
            f"<p><strong>Usuario:</strong> {username}<br/>"
            f"<strong>Senha temporaria:</strong> {temporary_password}</p>"
            "<p>No primeiro acesso voce devera alterar a senha.</p>"
            "<p>Se voce nao reconhece esta solicitacao, entre em contato com o suporte.</p>"
        )
        text_body = (
            f"Ola {full_name},\n\n"
            "Segue abaixo o seu acesso ao sistema NacionalSign:\n"
            f"Usuario: {username}\n"
            f"Senha temporaria: {temporary_password}\n\n"
            "No primeiro acesso voce devera alterar a senha.\n"
            "Se voce nao reconhece esta solicitacao, entre em contato com o suporte.\n"
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

    def send_usage_alert_email(
        self,
        *,
        recipients: Sequence[str],
        period_start: datetime,
        period_end: datetime,
        alerts: Sequence[dict[str, object]],
    ) -> None:
        if not recipients or not self._email_sender_available():
            raise RuntimeError("Email sender not configured")
        normalized_recipients: list[str] = []
        seen: set[str] = set()
        for email in recipients:
            if not email:
                continue
            normalized = email.strip()
            if not normalized:
                continue
            lower = normalized.lower()
            if lower in seen:
                continue
            seen.add(lower)
            normalized_recipients.append(normalized)
        if not normalized_recipients:
            raise RuntimeError("No recipients available for usage alert")

        rows = [
            {
                "tenant_name": entry.get("tenant_name"),
                "plan_name": entry.get("plan_name"),
                "documents_used": entry.get("documents_used"),
                "documents_signed": entry.get("documents_signed"),
                "documents_quota": entry.get("documents_quota"),
                "documents_percent": entry.get("documents_percent"),
                "documents_signed_percent": entry.get("documents_signed_percent"),
                "limit_state": entry.get("limit_state"),
                "limit_ratio": entry.get("limit_ratio"),
                "message": entry.get("message"),
            }
            for entry in alerts
        ]
        context = {
            "period_start": period_start,
            "period_end": period_end,
            "alerts": rows,
        }
        html_body = self._render_template("email/usage_alert.html", context)
        text_lines = [
            "Alertas de uso NacionalSign",
            f"Periodo: {period_start:%d/%m/%Y} ate {period_end:%d/%m/%Y}",
            "",
        ]
        if rows:
            for entry in rows:
                tenant = entry.get("tenant_name") or "Cliente"
                used = entry.get("documents_used") or 0
                quota = entry.get("documents_quota") or "infinito"
                state = entry.get("limit_state") or "ok"
                text_lines.append(f"- {tenant}: {used}/{quota} documentos (status: {state})")
        else:
            text_lines.append("Nenhum cliente atingiu o limite neste periodo.")
        text_lines.append("")
        text_lines.append("Equipe NacionalSign")
        text_body = "\n".join(text_lines)

        for email in normalized_recipients:
            self._send_email(
                to=email,
                subject="NacionalSign - Alertas de uso dos clientes",
                html_body=html_body,
                text_body=text_body,
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
        if self.email_backend == "sendgrid":
            if not self.sendgrid_config:
                raise RuntimeError("SendGrid sender not configured")
            self._send_email_via_sendgrid(
                to=to,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                attachments=list(attachments or []),
            )
            return
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

    def _send_email_via_sendgrid(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None,
        attachments: Sequence[EmailAttachment],
    ) -> None:
        if not self.sendgrid_config:
            raise RuntimeError("SendGrid sender not configured")
        sender = self.sendgrid_config.sender or (self.email_config.sender if self.email_config else None)
        if not sender:
            raise RuntimeError("SendGrid sender address missing")
        name, email = parseaddr(sender)
        if not email:
            raise RuntimeError("SendGrid sender address invalid")
        contents: list[dict[str, str]] = []
        if text_body:
            contents.append({"type": "text/plain", "value": text_body})
        contents.append({"type": "text/html", "value": html_body})
        payload: dict[str, object] = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": email},
            "subject": subject,
            "content": contents,
        }
        if name:
            payload["from"]["name"] = name
        if attachments:
            payload["attachments"] = [
                {
                    "content": base64.b64encode(item.content).decode("ascii"),
                    "type": item.mime_type or "application/octet-stream",
                    "filename": item.filename,
                    "disposition": "attachment",
                }
                for item in attachments
            ]
        headers = {
            "Authorization": f"Bearer {self.sendgrid_config.api_key}",
            "Content-Type": "application/json",
        }
        response = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
