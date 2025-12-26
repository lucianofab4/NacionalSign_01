from __future__ import annotations

import base64
import binascii
import hashlib
import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import UUID

from fastapi import UploadFile
from sqlmodel import Session, select
from sqlmodel import func

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.billing import Plan, Subscription
from app.models.document import (
    AuditArtifact,
    Document,
    DocumentField,
    DocumentParty,
    DocumentStatus,
    DocumentVersion,
)
from app.models.signing import SigningAgentAttempt, SigningAgentAttemptStatus
from app.models.tenant import Area
from app.models.tenant import Tenant
from app.models.user import User
from app.models.workflow import Signature, SignatureRequest, WorkflowInstance, WorkflowStep
from app.schemas.document import (
    DocumentCreate,
    DocumentFieldCreate,
    DocumentFieldUpdate,
    DocumentPartyCreate,
    DocumentUpdate,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from app.services.document_normalizer import normalize_to_pdf
from app.services.contact import ContactService
from app.services.icp import IcpIntegrationService, SignatureResult as IcpSignatureResult
from app.services.signing_agent import SigningAgentClient, build_sign_pdf_payload, decode_agent_pdf
from app.services.storage import (
    LocalStorage,
    StorageBackend,
    get_storage,
    normalize_storage_path,
    resolve_storage_root,
)
from app.schemas.signing_agent import SignPdfRequest

BASE_STORAGE = resolve_storage_root()
_PDF_SUPPORT: tuple[object, object] | None = None


class DocumentService:
    SIGNATURE_METHOD_ELECTRONIC = "electronic"
    SIGNATURE_METHOD_DIGITAL = "digital"
    _ALLOWED_SIGNATURE_METHODS = {SIGNATURE_METHOD_ELECTRONIC, SIGNATURE_METHOD_DIGITAL}

    def get_dashboard_metrics(
        self,
        current_user: User | None = None,
        area_id: UUID | None = None,
    ) -> dict[str, int]:
        tenant_id = getattr(current_user, "tenant_id", None)
        effective_area_id = area_id or getattr(current_user, "default_area_id", None)

        def with_common_filters(statement):
            if tenant_id:
                statement = statement.where(Document.tenant_id == tenant_id)
            if effective_area_id:
                statement = statement.where(Document.area_id == effective_area_id)
            return statement

        # Assinados na Ã¡rea (documentos concluÃ­dos)
        signed_query = with_common_filters(
            select(func.count()).where(Document.status == DocumentStatus.COMPLETED)
        )
        signed_in_area = self.session.exec(signed_query).one()

        # Pendentes na Ã¡rea (em revisÃ£o ou em andamento)
        pending_statuses = [DocumentStatus.IN_PROGRESS, DocumentStatus.IN_REVIEW]
        pending_area_query = with_common_filters(
            select(func.count()).where(Document.status.in_(pending_statuses))
        )
        pending_in_area = self.session.exec(pending_area_query).one()

        # Pendentes para o usuÃ¡rio (documentos onde o e-mail dele estÃ¡ entre as partes e ainda nÃ£o concluÃ­dos)
        email = (
            (current_user.email or "").strip().lower()
            if getattr(current_user, "email", None)
            else None
        )
        pending_for_user = 0
        if email:
            party_query = (
                select(func.count())
                .select_from(DocumentParty)
                .join(Document, DocumentParty.document_id == Document.id)
                .where(func.lower(DocumentParty.email) == email)
                .where(Document.status.in_(pending_statuses))
            )
            if tenant_id:
                party_query = party_query.where(Document.tenant_id == tenant_id)
            pending_for_user = self.session.exec(party_query).one()

        return {
            "pending_for_user": int(pending_for_user or 0),
            "to_sign": int(pending_for_user or 0),
            "signed_in_area": int(signed_in_area or 0),
            "pending_in_area": int(pending_in_area or 0),
        }

    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve_field_version_id(
        self,
        document: Document,
        version_id: UUID | None = None,
        role: str | None = None,
    ) -> UUID:
        """
        Returns the version that should be used for field lookups.
        Always prefer the provided version/current version, even if it has no fields yet.
        """
        target_id = version_id or document.current_version_id
        if not target_id:
            raise ValueError("Documento não tem versão atual")

        query = select(DocumentField.id).where(DocumentField.version_id == target_id)
        if role:
            query = query.where(DocumentField.role == role)

        _ = bool(self.session.exec(query.limit(1)).first())
        return target_id

    def _get_storage_backend(self) -> StorageBackend:
        storage = get_storage()
        override_base = BASE_STORAGE
        if override_base and isinstance(storage, LocalStorage):
            try:
                override_path = Path(override_base)
            except Exception:
                override_path = Path(str(override_base))

            current_base = getattr(storage, "base_dir", None)
            try:
                current_base_path = Path(current_base) if current_base else None
            except Exception:
                current_base_path = None

            if current_base_path != override_path:
                storage = LocalStorage(base_dir=override_path)
        return storage

    def _validate_signature_method(self, value: str | None) -> str:
        method = (value or self.SIGNATURE_METHOD_ELECTRONIC).strip().lower()
        if method not in self._ALLOWED_SIGNATURE_METHODS:
            raise ValueError("signature_method must be 'electronic' or 'digital'")
        return method

    def _ensure_unique_role(self, document: Document, role: str | None, *, ignore_party_id: UUID | None = None) -> None:
        normalized = (role or "").strip().lower()
        if not normalized:
            raise ValueError("Papel é obrigatório para o participante.")
        statement = (
            select(DocumentParty)
            .where(DocumentParty.document_id == document.id)
            .where(func.lower(DocumentParty.role) == normalized)
        )
        if ignore_party_id:
            statement = statement.where(DocumentParty.id != ignore_party_id)
        existing = self.session.exec(statement).first()
        if existing:
            raise ValueError("Já existe outro participante com este papel. Utilize nomes diferentes para cada papel.")

    @staticmethod
    def _normalize_cpf_value(value: str | None) -> str | None:
        if not value:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        return digits or None

    def _ensure_cpf_for_signature_method(self, method: str, cpf_value: str | None) -> None:
        normalized_method = self._validate_signature_method(method)
        if normalized_method != self.SIGNATURE_METHOD_DIGITAL:
            return

        normalized_cpf = self._normalize_cpf_value(cpf_value)
        if not normalized_cpf or len(normalized_cpf) != 11:
            raise ValueError("CPF é obrigatório para assinaturas com certificado digital.")

    def _build_protocol_summary(self, document: Document) -> list[str]:
        """
        Gera o conteúdo textual do protocolo de ações e assinaturas,
        incluindo todos os participantes com os dados de cadastro.
        """
        lines: list[str] = []
        margin = " " * 4

        version_hash: str | None = None
        if document.current_version_id:
            current_version = self.session.get(DocumentVersion, document.current_version_id)
            if current_version and current_version.sha256:
                version_hash = current_version.sha256
        if not version_hash:
            latest_version = (
                self.session.exec(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == document.id)
                    .order_by(DocumentVersion.created_at.desc())
                ).first()
            )
            if latest_version and latest_version.sha256:
                version_hash = latest_version.sha256

        lines.append("+" + "-" * 78 + "+")
        lines.append("|" + " PROTOCOLO DE AÇÕES E ASSINATURAS ".center(78) + "|")
        lines.append("+" + "-" * 78 + "+")
        lines.append("")
        lines.append(f"{margin}Documento.......: {document.name}")
        lines.append(f"{margin}Hash............: {version_hash or '-'}")
        if document.created_at:
            lines.append(f"{margin}Criado em.......: {document.created_at:%d/%m/%Y às %H:%M}")
        if document.updated_at:
            lines.append(f"{margin}Concluído em....: {document.updated_at:%d/%m/%Y às %H:%M}")
        lines.append("")

        parties = list(self.list_parties(document))
        if not parties:
            lines.append(f"{margin}Nenhum participante encontrado.")
            return lines

        signature_rows = self.session.exec(
            select(Signature, SignatureRequest, WorkflowStep, WorkflowInstance)
            .join(SignatureRequest, Signature.signature_request_id == SignatureRequest.id)
            .join(WorkflowStep, SignatureRequest.workflow_step_id == WorkflowStep.id)
            .join(WorkflowInstance, WorkflowStep.workflow_id == WorkflowInstance.id)
            .where(WorkflowInstance.document_id == document.id)
        ).all()

        signed_info: dict[UUID, dict[str, Any]] = {}

        def _guess_method(sig: Signature) -> str:
            if getattr(sig, "certificate_serial", None):
                return "digital (ICP-Brasil)"
            label = str(getattr(sig, "signature_type", "") or "").lower()
            if "digital" in label:
                return "digital (ICP-Brasil)"
            evidence = getattr(sig, "evidence_options", {}) or {}
            if evidence.get("certificate"):
                return "digital (ICP-Brasil)"
            return "eletrônica"

        for sig, _req, step, _wf in signature_rows:
            if not step.party_id:
                continue
            signed_info[step.party_id] = {
                "signed_at": sig.signed_at,
                "method": _guess_method(sig),
                "ip": sig.signer_ip,
            }

        for party in parties:
            if party.id not in signed_info and getattr(party, "signed_at", None):
                signed_info[party.id] = {
                    "signed_at": getattr(party, "signed_at"),
                    "method": "eletrônica",
                    "ip": getattr(party, "signer_ip", None),
                }

        lines.append("PARTICIPANTES E ASSINATURAS")
        lines.append("-" * 80)

        def _format_cnpj(value: str | None) -> str | None:
            if not value:
                return value
            digits = ''.join(ch for ch in value if ch.isdigit())
            if len(digits) != 14:
                return value
            return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

        def _format_cpf(value: str | None) -> str | None:
            if not value:
                return value
            digits = ''.join(ch for ch in value if ch.isdigit())
            if len(digits) != 11:
                return value
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

        for idx, party in enumerate(sorted(parties, key=lambda p: p.order_index or 0), 1):
            info = signed_info.get(party.id)

            if info:
                signed_at = info.get("signed_at")
                dt = signed_at.strftime("%d/%m/%Y às %H:%M") if signed_at else "?"
                method = info.get("method", "eletrônica")
                ip = f" | IP: {info.get('ip')}" if info.get("ip") else ""
                status_line = f"ASSINADO em {dt} — {method.upper()}{ip}"
            else:
                status_line = "PENDENTE DE ASSINATURA"

            lines.append(f"{margin}{idx:2}. {party.full_name or 'Nome não informado'}")
            if party.role:
                lines.append(f"{margin}    Papel..........: {party.role}")
            if party.company_name:
                lines.append(f"{margin}    Empresa........: {party.company_name}")
            if party.company_tax_id:
                cnpj_fmt = _format_cnpj(party.company_tax_id)
                lines.append(f"{margin}    CNPJ...........: {cnpj_fmt or party.company_tax_id}")
            if party.cpf:
                cpf_fmt = _format_cpf(party.cpf)
                lines.append(f"{margin}    CPF............: {cpf_fmt or party.cpf}")
            if party.email:
                lines.append(f"{margin}    E-mail.........: {party.email}")
            lines.append(f"{margin}    Status.........: {status_line}")
            lines.append("")

        lines.append("")
        lines.append("Este protocolo é parte integrante do documento e possui validade jurídica.")
        lines.append(f"Gerado pelo NacionalSign em {datetime.utcnow():%d/%m/%Y às %H:%M}")
        return lines

    def _enhance_electronic_signature_pdf(
        self,
        *,
        document: Document,
        original_bytes: bytes,
        signature_mode: str | None = None,
        document_fields: Sequence[DocumentField] | None = None,
        field_signatures: dict[str, dict[str, Any]] | None = None,
    ) -> bytes:
        """
        Aplica marca d'água discreta + acrescenta páginas de protocolo visual.
        """
        try:
            reader_cls, writer_cls = self._require_pdf_support()
        except ValueError:
            return original_bytes

        try:
            reader = reader_cls(io.BytesIO(original_bytes))
            writer = writer_cls()

            fields_by_id: dict[str, DocumentField] = {
                str(field.id): field for field in (document_fields or [])
            }
            page_field_map: dict[int, list[tuple[DocumentField, dict[str, Any]]]] = defaultdict(list)
            if field_signatures:
                for raw_id, data in field_signatures.items():
                    field = fields_by_id.get(str(raw_id))
                    if not field:
                        continue
                    page_index = int(getattr(field, "page", 1) or 1)
                    page_field_map[page_index].append((field, data))

            for page_index, page in enumerate(reader.pages, start=1):
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                overlay_stream = io.BytesIO()
                c = canvas.Canvas(overlay_stream, pagesize=(width, height))

                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(colors.HexColor("#4b5563"))
                header = "DOCUMENTO ASSINADO ELETRONICAMENTE / DIGITALMENTE - NacionalSign"
                c.drawString(40, height - 30, header)

                c.setFont("Helvetica", 7)
                c.setFillColor(colors.HexColor("#6b7280"))
                c.drawString(
                    40,
                    20,
                    f"Ref: {document.id} | Gerado em {datetime.utcnow():%d/%m/%Y %H:%M} (horário UTC)",
                )

                entries = page_field_map.get(page_index, []) if page_field_map else []
                for field, data in entries:
                    self._draw_field_signature(
                        c,
                        page_width=width,
                        page_height=height,
                        field=field,
                        data=data,
                    )

                c.save()
                overlay_stream.seek(0)
                overlay_reader = reader_cls(overlay_stream)
                page.merge_page(overlay_reader.pages[0])
                writer.add_page(page)

            protocol_lines = self._build_protocol_summary(document)
            proto_stream = io.BytesIO()
            c = canvas.Canvas(proto_stream, pagesize=A4)
            width, height = A4
            margin = 40
            line_height = 14
            y = height - margin - 30

            c.setFont("Helvetica-Bold", 16)
            c.drawCentredString(width / 2, height - margin, "PROTOCOLO DE AÇÕES E ASSINATURAS")
            c.setLineWidth(0.7)
            c.line(margin, height - margin - 12, width - margin, height - margin - 12)

            body_font = "Helvetica"
            body_size = 9
            max_text_width = width - 2 * margin
            c.setFont(body_font, body_size)
            for line in protocol_lines:
                wrapped = self._wrap_protocol_line(
                    line=line,
                    max_width=max_text_width,
                    font_name=body_font,
                    font_size=body_size,
                )
                for chunk in wrapped:
                    if y < margin + 40:
                        c.showPage()
                        y = height - margin - 30
                        c.setFont(body_font, body_size)
                    c.drawString(margin, y, chunk)
                    y -= line_height

            c.setFont("Helvetica-Oblique", 8)
            c.setFillColor(colors.HexColor("#4b5563"))
            c.drawCentredString(
                width / 2,
                30,
                "Documento com validade jurídica em conformidade com a MP 2.200-2/2001 e Lei 14.063/2020.",
            )
            c.save()

            proto_stream.seek(0)
            protocol_reader = reader_cls(proto_stream)
            for proto_page in protocol_reader.pages:
                writer.add_page(proto_page)

            output = io.BytesIO()
            writer.write(output)
            return output.getvalue()

        except Exception as exc:  # pragma: no cover - fallback em caso de falha
            logging.getLogger(__name__).warning(f"Falha ao gerar protocolo visual: {exc}")
            return original_bytes

    def _wrap_protocol_line(
        self,
        *,
        line: str,
        max_width: float,
        font_name: str,
        font_size: float,
    ) -> list[str]:
        if not line:
            return [""]

        stripped = line.lstrip(" ")
        indent_length = len(line) - len(stripped)
        indent = line[:indent_length]
        content = stripped

        if not content:
            return [indent]

        words = content.split(" ")
        segments: list[str] = []
        current: list[str] = []

        for word in words:
            if not word:
                continue
            candidate_words = current + [word]
            candidate_text = indent + " ".join(candidate_words)
            text_width = pdfmetrics.stringWidth(candidate_text, font_name, font_size)
            if text_width <= max_width or not current:
                current = candidate_words
                continue
            segments.append(indent + " ".join(current))
            current = [word]

        if current:
            segments.append(indent + " ".join(current))
        if not segments:
            segments.append(indent)
        return segments

    def apply_field_signature(
        self,
        document: Document,
        field: DocumentField,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if field.document_id != document.id:
            raise ValueError("Campo não pertence ao documento selecionado.")

        normalized_type = (field.field_type or "signature").strip().lower()
        typed_value = (payload.get("typed_name") or "").strip()
        if typed_value:
            typed_value = typed_value[:256]
        image_value = (payload.get("signature_image") or "").strip()

        result: dict[str, Any] = {
            "field_id": str(field.id),
            "field_type": field.field_type,
        }
        if typed_value:
            result["typed_name"] = typed_value
        if image_value:
            result["signature_image"] = image_value
            mime = (payload.get("signature_image_mime") or "image/png").strip() or "image/png"
            result["signature_image_mime"] = mime
            image_name = (payload.get("signature_image_name") or "").strip()
            if image_name:
                result["signature_image_name"] = image_name

        if normalized_type == "typed_name" and "typed_name" not in result:
            raise ValueError("Este campo exige um nome digitado.")
        if normalized_type == "signature_image" and "signature_image" not in result:
            raise ValueError("Este campo exige uma imagem de assinatura.")
        if normalized_type == "signature" and "typed_name" not in result and "signature_image" not in result:
            raise ValueError("Informe um valor para o campo de assinatura.")

        return result

    def _collect_field_signatures(self, document: Document) -> dict[str, dict[str, Any]]:
        statement = (
            select(Signature)
            .join(SignatureRequest, Signature.signature_request_id == SignatureRequest.id)
            .join(WorkflowStep, SignatureRequest.workflow_step_id == WorkflowStep.id)
            .join(WorkflowInstance, WorkflowStep.workflow_id == WorkflowInstance.id)
            .where(WorkflowInstance.document_id == document.id)
            .order_by(Signature.created_at.asc())
        )
        signatures = self.session.exec(statement).all()
        collected: dict[str, dict[str, Any]] = {}
        for signature in signatures:
            values = signature.field_values or {}
            if not isinstance(values, dict):
                continue
            for field_id, data in values.items():
                if not isinstance(data, dict):
                    continue
                collected[str(field_id)] = data
        return collected

    def _draw_field_signature(
        self,
        overlay: canvas.Canvas,
        *,
        page_width: float,
        page_height: float,
        field: DocumentField,
        data: dict[str, Any],
    ) -> None:
        width = max(float(field.width or 0.01), 0.01) * page_width
        height = max(float(field.height or 0.01), 0.01) * page_height
        x = max(float(field.x or 0.0), 0.0) * page_width
        x = min(max(0.0, x), max(0.0, page_width - width))
        top_offset = (float(field.y or 0.0) * page_height)
        y = page_height - top_offset - height
        y = min(max(0.0, y), max(0.0, page_height - height))

        image_payload = (data.get("signature_image") or "").strip()
        if image_payload:
            try:
                image_bytes = base64.b64decode(image_payload)
                reader = ImageReader(io.BytesIO(image_bytes))
                overlay.drawImage(reader, x, y, width=width, height=height, preserveAspectRatio=True, mask="auto")
                return
            except (binascii.Error, ValueError):
                pass

        typed_value = (data.get("typed_name") or "").strip()
        if not typed_value:
            return

        font_name = "Times-Roman"
        font_size = max(8, min(24, height * 0.4))
        text_width = pdfmetrics.stringWidth(typed_value, font_name, font_size)
        while text_width > width and font_size > 6:
            font_size -= 1
            text_width = pdfmetrics.stringWidth(typed_value, font_name, font_size)
        overlay.setFont(font_name, font_size)
        overlay.setFillColor(colors.HexColor("#111827"))
        text_x = x + width / 2
        text_y = y + (height - font_size) / 2
        overlay.drawCentredString(text_x, text_y + font_size / 2, typed_value)

    def list_documents(
        self,
        tenant_id: str | UUID,
        area_id: str | UUID | None = None,
        created_by_id: str | UUID | None = None,
    ) -> Iterable[Document]:
        tenant_uuid = UUID(str(tenant_id))
        statement = select(Document).where(Document.tenant_id == tenant_uuid)
        if area_id:
            statement = statement.where(Document.area_id == UUID(str(area_id)))
        if created_by_id:
            statement = statement.where(Document.created_by_id == UUID(str(created_by_id)))
        statement = statement.order_by(Document.updated_at.desc())
        return self.session.exec(statement).all()

    def get_document(self, tenant_id: str | UUID, document_id: str | UUID) -> Document | None:
        tenant_uuid = UUID(str(tenant_id))
        document = self.session.get(Document, UUID(str(document_id)))
        if document and document.tenant_id == tenant_uuid:
            return document
        return None

    def list_parties(self, document: Document) -> Iterable[DocumentParty]:
        statement = (
            select(DocumentParty)
            .where(DocumentParty.document_id == document.id)
            .order_by(DocumentParty.order_index)
        )
        return self.session.exec(statement).all()

    def add_party(self, document: Document, payload: DocumentPartyCreate) -> DocumentParty:
        data = payload.model_dump()
        channel = (data.get("notification_channel") or "email").lower()

        if channel not in {"email", "sms"}:
            raise ValueError("Unsupported notification channel")

        if channel == "email" and not data.get("email"):
            raise ValueError("Email required for email channel")
        if channel == "sms" and not data.get("phone_number"):
            raise ValueError("Phone number required for sms channel")

        data["notification_channel"] = channel
        data["full_name"] = data["full_name"].strip()
        if data.get("email"):
            data["email"] = data["email"].strip()
        if data.get("phone_number"):
            data["phone_number"] = data["phone_number"].strip()
        if data.get("role"):
            data["role"] = data["role"].strip()
        if "cpf" in data:
            data["cpf"] = self._normalize_cpf_value(data.get("cpf"))
        if data.get("company_name"):
            data["company_name"] = data["company_name"].strip()
        if data.get("company_tax_id"):
            digits = "".join(filter(str.isdigit, data["company_tax_id"]))
            data["company_tax_id"] = digits or None

        if not data.get("order_index") or data["order_index"] <= 0:
            max_index = self.session.exec(
                select(func.max(DocumentParty.order_index)).where(DocumentParty.document_id == document.id)
            ).one()
            next_index = (max_index or 0) + 1
            data["order_index"] = next_index

        data["signature_method"] = self._validate_signature_method(data.get("signature_method"))
        self._ensure_unique_role(document, data.get("role"))
        self._ensure_cpf_for_signature_method(data["signature_method"], data.get("cpf"))

        party = DocumentParty(document_id=document.id, **data)
        self.session.add(party)
        self._sync_contact_from_data(
            document.tenant_id,
            {
                "full_name": data.get("full_name"),
                "email": data.get("email"),
                "phone_number": data.get("phone_number"),
                "cpf": data.get("cpf"),
                "company_name": data.get("company_name"),
                "company_tax_id": data.get("company_tax_id"),
            },
        )
        self.session.commit()
        self.session.refresh(party)
        return party

    def update_party(self, party: DocumentParty, payload) -> DocumentParty:  # type: ignore[no-untyped-def]
        data = payload.model_dump(exclude_unset=True)
        if "notification_channel" in data and data["notification_channel"]:
            channel = data["notification_channel"].lower()
            if channel not in {"email", "sms"}:
                raise ValueError("Unsupported notification channel")
            if channel == "email" and not data.get("email", party.email):
                raise ValueError("Email required for email channel")
            if channel == "sms" and not data.get("phone_number", party.phone_number):
                raise ValueError("Phone number required for sms channel")
            data["notification_channel"] = channel

        if "full_name" in data and data["full_name"] is not None:
            data["full_name"] = data["full_name"].strip()
        if "email" in data and data["email"]:
            data["email"] = data["email"].strip()
        if "phone_number" in data and data["phone_number"]:
            data["phone_number"] = data["phone_number"].strip()
        if "cpf" in data:
            data["cpf"] = self._normalize_cpf_value(data["cpf"])
        if "role" in data and data["role"]:
            data["role"] = data["role"].strip()
        if "company_name" in data and data["company_name"]:
            data["company_name"] = data["company_name"].strip()
        if "company_tax_id" in data:
            value = data["company_tax_id"]
            if value:
                digits = "".join(filter(str.isdigit, value))
                data["company_tax_id"] = digits or None
            else:
                data["company_tax_id"] = None
        if "order_index" in data and data["order_index"]:
            if data["order_index"] <= 0:
                max_index = self.session.exec(
                    select(func.max(DocumentParty.order_index)).where(
                        DocumentParty.document_id == party.document_id
                    )
                ).one()
                data["order_index"] = (max_index or 0) + 1
        if "signature_method" in data:
            data["signature_method"] = self._validate_signature_method(data["signature_method"])

        document = self.session.get(Document, party.document_id)
        if not document:
            raise ValueError("Document not found for participant.")

        effective_role = data.get("role", party.role)
        effective_method = data.get("signature_method", party.signature_method)
        effective_cpf = data.get("cpf", party.cpf)
        self._ensure_unique_role(document, effective_role, ignore_party_id=party.id)
        self._ensure_cpf_for_signature_method(effective_method, effective_cpf)

        for field, value in data.items():
            setattr(party, field, value)

        self.session.add(party)
        self._sync_contact_from_data(
            document.tenant_id,
            {
                "full_name": party.full_name,
                "email": party.email,
                "phone_number": party.phone_number,
                "cpf": party.cpf,
                "company_name": party.company_name,
                "company_tax_id": party.company_tax_id,
            },
        )
        self.session.commit()
        self.session.refresh(party)
        return party

    def create_signing_agent_attempt(
        self,
        document: Document,
        version: DocumentVersion,
        *,
        actor_id: UUID | None,
        actor_role: str | None,
        payload: SignPdfRequest | dict[str, Any] | None,
    ) -> SigningAgentAttempt:
        payload_dict: dict[str, Any] | None = None
        if payload is not None:
            if isinstance(payload, SignPdfRequest):
                payload_dict = payload.model_dump(exclude_none=True)
            else:
                payload_dict = {key: value for key, value in payload.items() if value is not None}
        attempt = SigningAgentAttempt(
            document_id=document.id,
            version_id=version.id,
            actor_id=UUID(str(actor_id)) if actor_id else None,
            actor_role=actor_role,
            payload=payload_dict,
            status=SigningAgentAttemptStatus.PENDING,
        )
        self.session.add(attempt)
        self.session.commit()
        self.session.refresh(attempt)
        return attempt

    def finalize_signing_agent_attempt(
        self,
        attempt: SigningAgentAttempt,
        status: SigningAgentAttemptStatus,
        *,
        protocol: str | None = None,
        error_message: str | None = None,
        agent_details: dict[str, Any] | None = None,
    ) -> SigningAgentAttempt:
        attempt.status = status
        attempt.protocol = protocol
        attempt.error_message = error_message
        attempt.agent_details = agent_details
        attempt.updated_at = datetime.utcnow()
        self.session.add(attempt)
        self.session.commit()
        self.session.refresh(attempt)
        return attempt

    def get_latest_signing_agent_attempt(
        self,
        document: Document,
        version: DocumentVersion,
    ) -> SigningAgentAttempt | None:
        return self.session.exec(
            select(SigningAgentAttempt)
            .where(SigningAgentAttempt.document_id == document.id)
            .where(SigningAgentAttempt.version_id == version.id)
            .order_by(SigningAgentAttempt.created_at.desc())
        ).first()

    def create_document(
        self,
        tenant_id: str | UUID,
        user_id: str | UUID,
        payload: DocumentCreate,
    ) -> Document:
        tenant_uuid = UUID(str(tenant_id))
        area_uuid = UUID(str(payload.area_id))

        area = self.session.get(Area, area_uuid)
        if not area or area.tenant_id != tenant_uuid:
            raise ValueError("Area does not belong to tenant")

        # Enforce plan document quota (best-effort)
        subscription = self.session.exec(
            select(Subscription).where(Subscription.tenant_id == tenant_uuid)
        ).first()
        if subscription:
            plan = self.session.get(Plan, subscription.plan_id)
            if plan and plan.document_quota is not None and plan.document_quota > 0:
                # count documents created in the current billing period (since valid_until - 30d)
                period_start = (subscription.valid_until or datetime.utcnow()) - timedelta(days=30)
                total_docs = self.session.exec(
                    select(func.count()).select_from(Document).where(
                        (Document.tenant_id == tenant_uuid) & (Document.created_at >= period_start)
                    )
                ).one()
                # SQLModel returns tuple-like; guard for int
                current_docs = int(total_docs or 0)
                if current_docs >= plan.document_quota:
                    raise ValueError("Document quota exceeded for current plan")

        # Optional wallet consumption enforcement
        if getattr(settings, "billing_use_wallet", False):
            tenant = self.session.get(Tenant, tenant_uuid)
            if not tenant:
                raise ValueError("Tenant not found")
            if (tenant.balance_cents or 0) <= 0:
                raise ValueError("Saldo insuficiente para criar documento")

            # Debita 1 unidade por documento (pode ser configurÃ¡vel no futuro)
            tenant.balance_cents = max(int(tenant.balance_cents or 0) - 1, 0)
            self.session.add(tenant)

        flow_mode = payload.signature_flow_mode or "SEQUENTIAL"

        document = Document(
            tenant_id=tenant_uuid,
            area_id=area_uuid,
            name=payload.name,
            status=DocumentStatus.DRAFT,
            signature_flow_mode=flow_mode,
            created_by_id=UUID(str(user_id)),
        )
        self.session.add(document)
        self.session.commit()
        self.session.refresh(document)
        return document

    async def add_version(
        self,
        document: Document,
        user_id: str | UUID,
        files: Sequence[UploadFile],
    ) -> DocumentVersion:
        uploads = [item for item in files if item is not None]
        if not uploads:
            raise ValueError("Nenhum arquivo foi enviado.")

        normalized_items: list[tuple[Any, bytes, UploadFile]] = []
        for upload in uploads:
            contents = await upload.read()
            if not contents:
                continue
            try:
                normalized = normalize_to_pdf(upload.filename, upload.content_type, contents)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            normalized_items.append((normalized, contents, upload))

        if not normalized_items:
            raise ValueError("Arquivos enviados estÃ£o vazios ou invÃ¡lidos.")

        if len(normalized_items) == 1:
            normalized, _, _ = normalized_items[0]
            final_pdf = normalized.pdf_bytes
            final_name = normalized.filename
        else:
            reader_cls, writer_cls = self._require_pdf_support()
            writer = writer_cls()
            for normalized, _, _ in normalized_items:
                reader = reader_cls(io.BytesIO(normalized.pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)
            buffer = io.BytesIO()
            writer.write(buffer)
            final_pdf = buffer.getvalue()
            final_name = f"{document.name}-unificado.pdf"

        pdf_sha256 = hashlib.sha256(final_pdf).hexdigest()
        root = f"documents/{document.tenant_id}/{document.id}"
        storage = self._get_storage_backend()
        storage_name = f"{pdf_sha256}.pdf"
        storage_path_str = storage.save_bytes(root=root, name=storage_name, data=final_pdf)
        storage_path_str = normalize_storage_path(storage_path_str)

        version = DocumentVersion(
            document_id=document.id,
            storage_path=storage_path_str,
            original_filename=final_name,
            mime_type="application/pdf",
            size_bytes=len(final_pdf),
            sha256=pdf_sha256,
            uploaded_by_id=UUID(str(user_id)),
        )
        self.session.add(version)
        self.session.flush()

        document.current_version_id = version.id
        document.status = DocumentStatus.IN_REVIEW
        self.session.add(document)

        multiple_sources = len(normalized_items) > 1
        for normalized, contents, upload in normalized_items:
            if normalized.converted or multiple_sources:
                source_sha = hashlib.sha256(contents).hexdigest()
                source_ext = Path(upload.filename or normalized.filename or "").suffix or ".bin"
                source_name = f"source-{source_sha}{source_ext}"
                source_path = storage.save_bytes(root=root, name=source_name, data=contents)
                source_path = normalize_storage_path(source_path)
                artifact = AuditArtifact(
                    document_id=document.id,
                    artifact_type="original_upload",
                    storage_path=source_path,
                    sha256=source_sha,
                )
                self.session.add(artifact)

        self.session.commit()
        self.session.refresh(version)
        self.session.refresh(document)
        return version

    def _require_pdf_support(self) -> tuple[object, object]:
        global _PDF_SUPPORT
        if _PDF_SUPPORT is not None:
            return _PDF_SUPPORT
        try:
            from pypdf import PdfReader as _Reader, PdfWriter as _Writer  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ValueError(
                "Biblioteca 'pypdf' indisponível para unificar arquivos. "
                "Instale o pacote 'pypdf' e reinicie o servidor."
            ) from exc
        _PDF_SUPPORT = (_Reader, _Writer)
        return _PDF_SUPPORT

    def update_document(self, document: Document, payload: DocumentUpdate) -> Document:
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == "status" and value is not None:
                value = DocumentStatus(value)
            setattr(document, field, value)
        self.session.add(document)
        self.session.commit()
        self.session.refresh(document)
        return document

    def ensure_final_signed_version(
        self,
        document: Document,
    ) -> tuple[DocumentVersion, AuditArtifact | None, IcpSignatureResult | None]:
        """
        Gera a versão final assinada quando o workflow é concluído.
        """
        if not document.current_version_id:
            raise ValueError("Document has no version to finalize")

        current_version = self.session.get(DocumentVersion, document.current_version_id)
        if not current_version:
            raise ValueError("Current version not found for document")

        field_version_id = self.resolve_field_version_id(document, document.current_version_id)
        document_fields: list[DocumentField] = []
        if field_version_id:
            document_fields = self.session.exec(
                select(DocumentField)
                .where(DocumentField.document_id == document.id)
                .where(DocumentField.version_id == field_version_id)
            ).all()
        field_signatures = self._collect_field_signatures(document)

        filename = (Path(current_version.storage_path).name or "").lower()
        if filename.startswith("final-"):
            return current_version, None, None

        storage = self._get_storage_backend()
        original_bytes = storage.load_bytes(current_version.storage_path)

        pkcs_sources: list[tuple[AuditArtifact, bytes]] = []
        if current_version.sha256:
            pkcs_artifacts = self.session.exec(
                select(AuditArtifact)
                .where(AuditArtifact.document_id == document.id)
                .where(AuditArtifact.artifact_type == "signed_pdf_pkcs7")
                .order_by(AuditArtifact.created_at.desc())
            ).all()
            for artifact in pkcs_artifacts:
                path_value = artifact.storage_path or ""
                if not path_value or current_version.sha256 not in path_value:
                    continue
                try:
                    content = storage.load_bytes(path_value)
                except Exception:
                    continue
                pkcs_sources.append((artifact, content))

        logger = logging.getLogger("nacionalsign.icp")
        icp_result: IcpSignatureResult | None = None
        timestamp_artifact: AuditArtifact | None = None

        try:
            icp_service = IcpIntegrationService(self.session)
            icp_result = icp_service.apply_security(
                pdf_bytes=original_bytes,
                document=document,
                version=current_version,
            )
            signed_bytes = icp_result.signed_pdf or original_bytes
        except Exception as exc:  # pragma: no cover - robustez
            logger.warning(f"Falha na integração ICP: {exc}")
            signed_bytes = original_bytes
            icp_result = None

        final_pdf = self._enhance_electronic_signature_pdf(
            document=document,
            original_bytes=signed_bytes,
            signature_mode="electronic",
            document_fields=document_fields,
            field_signatures=field_signatures,
        )
        final_sha256 = hashlib.sha256(final_pdf).hexdigest()

        storage_root = f"documents/{document.tenant_id}/{document.id}"
        final_path = storage.save_bytes(
            root=storage_root,
            name=f"final-{final_sha256}.pdf",
            data=final_pdf,
        )
        final_path = normalize_storage_path(final_path)

        if pkcs_sources:
            final_base_name = Path(final_path).name
            for idx, (artifact, content) in enumerate(pkcs_sources, start=1):
                suffix = "" if idx == 1 else f"-{idx - 1}"
                pkcs_name = f"{final_base_name}{suffix}.p7s"
                try:
                    pkcs_path = storage.save_bytes(
                        root=storage_root,
                        name=pkcs_name,
                        data=content,
                    )
                    pkcs_path = normalize_storage_path(pkcs_path)
                    artifact.storage_path = pkcs_path
                    artifact.issued_at = artifact.issued_at or datetime.utcnow()
                    self.session.add(artifact)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(f"Falha ao copiar PKCS7 para versao final: {exc}")

        base_label = Path(current_version.original_filename or f"{document.id}.pdf").stem
        final_filename = f"{base_label}-assinatura-final.pdf"
        signed_version = DocumentVersion(
            document_id=document.id,
            storage_path=final_path,
            original_filename=final_filename,
            mime_type="application/pdf",
            size_bytes=len(final_pdf),
            sha256=final_sha256,
            uploaded_by_id=current_version.uploaded_by_id or document.created_by_id,
        )
        self.session.add(signed_version)
        self.session.flush()

        if icp_result and icp_result.timestamp and icp_result.timestamp.token:
            try:
                token_bytes = icp_result.timestamp.token
                ts_name = f"timestamp-{final_sha256}.tsr"
                ts_path = storage.save_bytes(root=storage_root, name=ts_name, data=token_bytes)
                ts_path = normalize_storage_path(ts_path)
                timestamp_artifact = AuditArtifact(
                    document_id=document.id,
                    artifact_type="timestamp_token",
                    storage_path=ts_path,
                    sha256=hashlib.sha256(token_bytes).hexdigest(),
                    issued_at=icp_result.timestamp.issued_at or datetime.utcnow(),
                )
                self.session.add(timestamp_artifact)
                self.session.flush()
            except Exception as exc:  # pragma: no cover - robustez
                logger.warning(f"Falha ao salvar token de carimbo de tempo: {exc}")
                timestamp_artifact = None

        document.current_version_id = signed_version.id
        document.status = DocumentStatus.COMPLETED
        self.session.add(document)
        self.session.commit()
        self.session.refresh(signed_version)

        return signed_version, timestamp_artifact, icp_result

    def sign_version_with_agent(
        self,
        document: Document,
        version: DocumentVersion,
        request: SignPdfRequest,
        user_id: str | UUID,
    ) -> tuple[DocumentVersion, dict[str, Any]]:
        logger = logging.getLogger("nacionalsign.sign")
        logger.info(
            f"[sign_version_with_agent] Iniciando assinatura para documento={document.id}, version={version.id}"
        )

        if version.document_id != document.id:
            logger.error("VersÃ£o nÃ£o pertence ao documento informado.")
            raise ValueError("VersÃ£o nÃ£o pertence ao documento informado.")
        if version.mime_type != "application/pdf":
            logger.error("A versÃ£o atual nÃ£o Ã© um PDF.")
            raise ValueError("A versÃ£o atual nÃ£o Ã© um PDF.")

        # Monta payload para o agente
        payload = self.build_signing_agent_payload(document, version, request, logger=logger)

        # Chama o agente local
        client = SigningAgentClient()
        agent_response = client.sign_pdf(payload)

        # Decodifica resposta do agente (PDF + PKCS#7 opcional)
        decoded = decode_agent_pdf(agent_response)
        signed_pdf_bytes: bytes = decoded["pdf"]
        pkcs7_bytes: bytes | None = decoded.get("p7s")

        logger.info(
            f"[sign_version_with_agent] PDF assinado recebido do agente ({len(signed_pdf_bytes)} bytes)"
        )

        # Persiste a nova versÃ£o e, se existir, o .p7s como artefato
        signed_version = self._persist_signed_pdf(
            document,
            version,
            signed_pdf_bytes,
            user_id,
            logger=logger,
            pkcs7_bytes=pkcs7_bytes,
        )
        logger.info(
            f"[sign_version_with_agent] Processo finalizado com sucesso para documento={document.id}, version={signed_version.id}"
        )

        return signed_version, agent_response

    def build_signing_agent_payload(
        self,
        document: Document,
        version: DocumentVersion,
        request: SignPdfRequest,
        *,
        logger: logging.Logger | None = None,
    ) -> dict[str, Any]:
        storage = self._get_storage_backend()
        pdf_bytes = storage.load_bytes(version.storage_path)
        if logger:
            logger.info(
                f"[build_signing_agent_payload] PDF carregado de {version.storage_path} ({len(pdf_bytes)} bytes)"
            )

        return build_sign_pdf_payload(
            pdf_bytes=pdf_bytes,
            cert_index=request.cert_index,
            thumbprint=request.thumbprint,
            protocol=request.protocol,
            watermark=request.watermark,
            footer_note=request.footer_note,
            actions=request.actions,
            signature_type=request.signature_type,
            authentication=request.authentication,
            certificate_description=request.certificate_description,
            token_info=request.token_info,
            signature_page=request.signature_page,
            signature_width=request.signature_width,
            signature_height=request.signature_height,
            signature_margin_x=request.signature_margin_x,
            signature_margin_y=request.signature_margin_y,
        )

    def save_signed_pdf_from_agent_response(
        self,
        document: Document,
        version: DocumentVersion,
        agent_response: dict[str, Any],
        user_id: str | UUID | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> DocumentVersion:
        """
        Salva um PDF jÃ¡ assinado a partir da resposta crua do agente.

        Ãtil quando a chamada ao agente jÃ¡ foi feita em outro ponto
        e temos apenas o JSON de resposta em mÃ£os.
        """
        decoded = decode_agent_pdf(agent_response)

        signed_pdf_bytes: bytes = decoded["pdf"]
        pkcs7_bytes: bytes | None = decoded.get("p7s")

        if logger:
            logger.info(
                f"[save_signed_pdf_from_agent_response] PDF assinado recebido ({len(signed_pdf_bytes)} bytes)"
            )

        return self._persist_signed_pdf(
            document,
            version,
            signed_pdf_bytes,
            user_id,
            logger=logger,
            pkcs7_bytes=pkcs7_bytes,
        )


    def _persist_signed_pdf(
        self,
        document: Document,
        version: DocumentVersion,
        signed_pdf: bytes,
        user_id: str | UUID | None = None,
        *,
        logger: logging.Logger | None = None,
        pkcs7_bytes: bytes | None = None,
    ) -> DocumentVersion:
        """
        Persiste a versão intermediária assinada (sem protocolo visual) e,
        opcionalmente, o arquivo PKCS#7 (.p7s) como artefato.
        """
        storage = self._get_storage_backend()
        storage_root = f"documents/{document.tenant_id}/{document.id}"

        stored_sha256 = hashlib.sha256(signed_pdf).hexdigest()
        stored_path = storage.save_bytes(
            root=storage_root,
            name=f"signed-{stored_sha256}.pdf",
            data=signed_pdf,
        )
        stored_path = normalize_storage_path(stored_path)

        base_label = Path(version.original_filename or f"{document.id}.pdf").stem
        signed_version = DocumentVersion(
            document_id=document.id,
            storage_path=stored_path,
            original_filename=f"{base_label}-assinado-parcial.pdf",
            mime_type="application/pdf",
            size_bytes=len(signed_pdf),
            sha256=stored_sha256,
            uploaded_by_id=UUID(str(user_id)) if user_id else version.uploaded_by_id,
        )
        self.session.add(signed_version)
        self.session.flush()

        if pkcs7_bytes:
            try:
                p7s_path = storage.save_bytes(
                    root=storage_root,
                    name=f"signed-{stored_sha256}.pdf.p7s",
                    data=pkcs7_bytes,
                )
                p7s_path = normalize_storage_path(p7s_path)
                artifact = AuditArtifact(
                    document_id=document.id,
                    artifact_type="signed_pdf_pkcs7",
                    storage_path=p7s_path,
                    sha256=hashlib.sha256(pkcs7_bytes).hexdigest(),
                    issued_at=datetime.utcnow(),
                )
                self.session.add(artifact)
                self.session.flush()
            except Exception as exc:
                if logger:
                    logger.warning(f"Falha ao salvar .p7s: {exc}")

        document.current_version_id = signed_version.id
        self.session.add(document)
        self.session.commit()
        self.session.refresh(signed_version)
        return signed_version

    def list_fields(self, document: Document, version: DocumentVersion) -> list[DocumentField]:
        """
        Retorna todos os campos (DocumentField) daquela versÃ£o do documento,
        ordenados por pÃ¡gina e data de criaÃ§Ã£o.
        """
        statement = (
            select(DocumentField)
            .where(DocumentField.document_id == document.id)
            .where(DocumentField.version_id == version.id)
            .order_by(DocumentField.page, DocumentField.created_at)
        )
        return self.session.exec(statement).all()

    def create_field(
        self,
        document: Document,
        version: DocumentVersion,
        payload: DocumentFieldCreate,
    ) -> DocumentField:
        if version.document_id != document.id:
            raise ValueError("Version does not belong to document")

        data = payload.model_dump()
        field = DocumentField(
            document_id=document.id,
            version_id=version.id,
            **data,
        )
        self.session.add(field)
        self.session.commit()
        self.session.refresh(field)
        return field

    def update_field(
        self,
        field: DocumentField,
        payload: DocumentFieldUpdate,
    ) -> DocumentField:
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(field, key, value)
        self.session.add(field)
        self.session.commit()
        self.session.refresh(field)
        return field

    def delete_field(self, field: DocumentField) -> None:
        self.session.delete(field)
        self.session.commit()

    def archive_document(self, document: Document) -> Document:
        if document.status == DocumentStatus.ARCHIVED:
            return document
        document.last_active_status = document.status
        document.status = DocumentStatus.ARCHIVED
        document.updated_at = datetime.utcnow()
        self.session.add(document)
        self.session.commit()
        self.session.refresh(document)
        return document

    def unarchive_document(self, document: Document) -> Document:
        previous_status = document.last_active_status or DocumentStatus.IN_REVIEW
        document.status = previous_status
        document.last_active_status = None
        document.updated_at = datetime.utcnow()
        self.session.add(document)
        self.session.commit()
        self.session.refresh(document)
        return document

    def delete_document(self, document: Document) -> None:
        """Remove documento, versÃµes, partes, campos, artefatos e workflows relacionados."""
        # Remove workflows e assinaturas
        self._delete_workflows(document.id)

        # Remove parties
        parties = self.session.exec(
            select(DocumentParty).where(DocumentParty.document_id == document.id)
        ).all()
        for party in parties:
            self.session.delete(party)

        # Remove document fields
        fields = self.session.exec(
            select(DocumentField).where(DocumentField.document_id == document.id)
        ).all()
        for field in fields:
            self.session.delete(field)

        if document.current_version_id:
            document.current_version_id = None
            self.session.add(document)
            self.session.flush()

        # Remove versions
        versions = self.session.exec(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id)
        ).all()
        for version in versions:
            attempts = self.session.exec(
                select(SigningAgentAttempt).where(SigningAgentAttempt.version_id == version.id)
            ).all()
            for attempt in attempts:
                self.session.delete(attempt)
            self.session.delete(version)

        # Remove audit artifacts
        artifacts = self.session.exec(
            select(AuditArtifact).where(AuditArtifact.document_id == document.id)
        ).all()
        for artifact in artifacts:
            self.session.delete(artifact)

        # Remove audit logs relacionados
        audit_logs = self.session.exec(
            select(AuditLog).where(AuditLog.document_id == document.id)
        ).all()
        for log in audit_logs:
            self.session.delete(log)

        # Finalmente, remove o documento
        self.session.delete(document)
        self.session.commit()

    def _delete_workflows(self, document_id: UUID) -> None:
        """Remove workflows, etapas, requests e assinaturas ligadas ao documento."""
        workflows = self.session.exec(
            select(WorkflowInstance).where(WorkflowInstance.document_id == document_id)
        ).all()

        for workflow in workflows:
            steps = self.session.exec(
                select(WorkflowStep).where(WorkflowStep.workflow_id == workflow.id)
            ).all()

            for step in steps:
                requests = self.session.exec(
                    select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
                ).all()

                for request in requests:
                    signatures = self.session.exec(
                        select(Signature).where(Signature.signature_request_id == request.id)
                    ).all()
                    for signature in signatures:
                        self.session.delete(signature)
                    self.session.delete(request)

                self.session.delete(step)

            self.session.delete(workflow)

    def _sync_contact_from_data(self, tenant_id: UUID, payload: dict[str, Any]) -> None:
        try:
            contact_service = ContactService(self.session)
            contact_service.upsert_from_payload(tenant_id, payload)
        except Exception:
            logging.getLogger(__name__).warning("Falha ao sincronizar contato", exc_info=True)
