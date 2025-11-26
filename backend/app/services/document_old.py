from __future__ import annotations

import io
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from fastapi import UploadFile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
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
from app.schemas.document import (
    DocumentCreate,
    DocumentFieldCreate,
    DocumentFieldUpdate,
    DocumentPartyCreate,
    DocumentUpdate,
)
from app.services.document_normalizer import normalize_to_pdf
from app.services.icp import IcpIntegrationService
from app.services.icp import SignatureResult as IcpSignatureResult
from app.services.signing_agent import SigningAgentClient, build_sign_pdf_payload, decode_agent_pdf
from app.services.storage import get_storage, normalize_storage_path, resolve_storage_root
from app.schemas.signing_agent import SignPdfRequest

try:  # pragma: no cover - optional dependency
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment]
    PdfWriter = None  # type: ignore[assignment]

BASE_STORAGE = resolve_storage_root()


class DocumentService:
    SIGNATURE_METHOD_ELECTRONIC = \"electronic\"
    SIGNATURE_METHOD_DIGITAL = \"digital\"
    _ALLOWED_SIGNATURE_METHODS = {SIGNATURE_METHOD_ELECTRONIC, SIGNATURE_METHOD_DIGITAL}
    def get_dashboard_metrics(self, current_user=None, area_id=None):
        """
        ImplementaÃ§Ã£o mÃ­nima para evitar erro 500 ao carregar o dashboard.
        Retorna zeros para todos os campos.
        """
        return {
            "pending_for_user": 0,
            "to_sign": 0,
            "signed_in_area": 0,
            "pending_in_area": 0,
        }
    def __init__(self, session: Session) -> None:
        self.session = session
    def _validate_signature_method(self, value: str | None) -> str:
        method = (value or self.SIGNATURE_METHOD_ELECTRONIC).strip().lower()
        if method not in self._ALLOWED_SIGNATURE_METHODS:
            raise ValueError("signature_method must be 'electronic' or 'digital'")
        return method

    def _build_protocol_summary(self, document: Document) -> list[str]:
        rows = (
            self.session.exec(
                select(AuditLog)
                .where(AuditLog.document_id == document.id)
                .order_by(AuditLog.created_at.asc())
            ).all()
            if AuditLog is not None
            else []
        )
        lines = [f"Documento: {document.name}", f"Referência: {document.id}"]
        if document.updated_at:
            lines.append(f"Atualizado em: {document.updated_at:%d/%m/%Y %H:%M}")
        lines.append(" ")
        for row in rows[-15:]:
            created = row.created_at.strftime("%d/%m/%Y %H:%M") if row.created_at else "-"
            event = (row.event_type or "").replace("_", " ")
            lines.append(f"{created} - {event}")
        return lines

    def _enhance_electronic_signature_pdf(self, *, document: Document, original_bytes: bytes) -> bytes:
        if not PdfReader or not PdfWriter:
            return original_bytes
        try:
            reader = PdfReader(io.BytesIO(original_bytes))
        except Exception:
            return original_bytes

        try:
            writer = PdfWriter()
            protocol_lines = self._build_protocol_summary(document)
            watermark_text = "Documento assinado eletronicamente"
            footer_lines = [
                f"Documento: {document.name}",
                f"Referência: {document.id}",
            ]

            for page_index, page in enumerate(reader.pages):
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                overlay_stream = io.BytesIO()
                overlay = canvas.Canvas(overlay_stream, pagesize=(width, height))
                overlay.saveState()
                overlay.translate(width / 2.0, height / 2.0)
                overlay.rotate(45)
                overlay.setFont("Helvetica-Bold", 36)
                overlay.setFillColorRGB(0.80, 0.80, 0.80)
                overlay.drawCentredString(0, 0, watermark_text)
                overlay.restoreState()

                overlay.setFont("Helvetica", 9)
                overlay.setFillColor(colors.HexColor("#1f2937"))
                if page_index == 0:
                    y = 32
                    for line in footer_lines:
                        overlay.drawString(36, y, line)
                        y += 12

                overlay.save()
                overlay_stream.seek(0)
                overlay_reader = PdfReader(overlay_stream)
                page.merge_page(overlay_reader.pages[0])
                writer.add_page(page)

            if protocol_lines:
                proto_stream = io.BytesIO()
                proto_canvas = canvas.Canvas(proto_stream, pagesize=A4)
                proto_canvas.setFont("Helvetica-Bold", 16)
                proto_canvas.drawString(40, 800, "Protocolo de ações")
                proto_canvas.setFont("Helvetica", 10)
                y = 770
                for line in protocol_lines:
                    if y < 40:
                        proto_canvas.showPage()
                        proto_canvas.setFont("Helvetica", 10)
                        y = 800
                    proto_canvas.drawString(40, y, line)
                    y -= 14
                proto_canvas.save()
                proto_stream.seek(0)
                protocol_reader = PdfReader(proto_stream)
                for proto_page in protocol_reader.pages:
                    writer.add_page(proto_page)

            output = io.BytesIO()
            writer.write(output)
            return output.getvalue()
        except Exception:
            return original_bytes

    def list_documents(self, tenant_id: str | UUID, area_id: str | UUID | None = None) -> Iterable[Document]:
        tenant_uuid = UUID(str(tenant_id))
        statement = select(Document).where(Document.tenant_id == tenant_uuid)
        if area_id:
            statement = statement.where(Document.area_id == UUID(str(area_id)))
        return self.session.exec(statement).all()

    def get_document(self, tenant_id: str | UUID, document_id: str | UUID) -> Document | None:
        tenant_uuid = UUID(str(tenant_id))
        document = self.session.get(Document, UUID(str(document_id)))
        if document and document.tenant_id == tenant_uuid:
            return document
        return None

    def list_parties(self, document: Document) -> Iterable[DocumentParty]:
        statement = select(DocumentParty).where(DocumentParty.document_id == document.id).order_by(DocumentParty.order_index)
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
        if data.get("cpf"):
            data["cpf"] = data["cpf"].strip()
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

        party = DocumentParty(document_id=document.id, **data)
        self.session.add(party)
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
        if "cpf" in data and data["cpf"]:
            data["cpf"] = data["cpf"].strip()
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
                    select(func.max(DocumentParty.order_index)).where(DocumentParty.document_id == party.document_id)
                ).one()
                data["order_index"] = (max_index or 0) + 1
        if "signature_method" in data:
            data["signature_method"] = self._validate_signature_method(data["signature_method"])

        for field, value in data.items():
            setattr(party, field, value)

        self.session.add(party)
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

        document = Document(
            tenant_id=tenant_uuid,
            area_id=area_uuid,
            name=payload.name,
            status=DocumentStatus.DRAFT,
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
        file: UploadFile,
    ) -> DocumentVersion:
        contents = await file.read()
        try:
            normalized = normalize_to_pdf(file.filename, file.content_type, contents)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        pdf_bytes = normalized.pdf_bytes
        pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        root = f"documents/{document.tenant_id}/{document.id}"
        storage = get_storage()
        storage_name = f"{pdf_sha256}.pdf"
        storage_path_str = storage.save_bytes(root=root, name=storage_name, data=pdf_bytes)
        storage_path_str = normalize_storage_path(storage_path_str)

        version = DocumentVersion(
            document_id=document.id,
            storage_path=storage_path_str,
            original_filename=normalized.filename,
            mime_type="application/pdf",
            size_bytes=len(pdf_bytes),
            sha256=pdf_sha256,
            uploaded_by_id=UUID(str(user_id)),
        )
        self.session.add(version)
        self.session.flush()

        document.current_version_id = version.id
        document.status = DocumentStatus.IN_REVIEW
        self.session.add(document)

        if normalized.converted:
            source_sha = hashlib.sha256(contents).hexdigest()
            source_ext = Path(file.filename or "").suffix or ".bin"
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
        """Create a final signed PDF version when the workflow completes.

        Returns the active version, optional timestamp artifact, and the signature result.
        If the current version is already a signed artifact (final-*), the existing version is returned.
        """
        if not document.current_version_id:
            raise ValueError("Document has no version to finalize")

        current_version = self.session.get(DocumentVersion, document.current_version_id)
        if not current_version:
            raise ValueError("Current version not found for document")

        file_name = Path(current_version.storage_path).name.lower()
        if file_name.startswith("final-"):
            self.session.refresh(current_version)
            return current_version, None, None

        if current_version.mime_type != "application/pdf":
            raise ValueError("Current version is not a PDF; normalize before signing")

        storage = get_storage()
        original_bytes = storage.load_bytes(current_version.storage_path)

        icp_service = IcpIntegrationService.from_settings(settings)
        signature_result = icp_service.apply_security(
            original_bytes,
            reason=settings.icp_signature_reason,
            location=settings.icp_signature_location,
        )

        if "signer-missing" in (signature_result.warnings or []):
            enhanced_pdf = self._enhance_electronic_signature_pdf(document=document, original_bytes=original_bytes)
            signature_result.signed_pdf = enhanced_pdf
            signature_result.sha256 = hashlib.sha256(enhanced_pdf).hexdigest()

        storage_root = f"documents/{document.tenant_id}/{document.id}"        signed_file_name = f"final-{signature_result.sha256}.pdf"
        signed_storage_path = storage.save_bytes(
            root=storage_root,
            name=signed_file_name,
            data=signature_result.signed_pdf,
        )
        signed_storage_path = normalize_storage_path(signed_storage_path)

        base_label = Path(current_version.original_filename or f"{document.id}.pdf").stem
        signed_original_name = f"{base_label}-assinatura-final.pdf"

        signed_version = DocumentVersion(
            document_id=document.id,
            storage_path=signed_storage_path,
            original_filename=signed_original_name,
            mime_type="application/pdf",
            size_bytes=len(signature_result.signed_pdf),
            sha256=signature_result.sha256,
            uploaded_by_id=document.created_by_id,
        )
        self.session.add(signed_version)
        self.session.flush()

        document.current_version_id = signed_version.id
        document.status = DocumentStatus.COMPLETED
        self.session.add(document)

        timestamp_artifact: AuditArtifact | None = None
        if signature_result.timestamp and signature_result.timestamp.token:
            token_name = f"final-{signature_result.sha256}.tsr"
            token_path = storage.save_bytes(
                root=storage_root,
                name=token_name,
                data=signature_result.timestamp.token,
            )
            token_path = normalize_storage_path(token_path)
            issued_at = signature_result.timestamp.issued_at
            timestamp_artifact = AuditArtifact(
                document_id=document.id,
                artifact_type="signed_pdf_timestamp",
                storage_path=token_path,
                sha256=hashlib.sha256(signature_result.timestamp.token).hexdigest(),
                issued_at=issued_at.replace(tzinfo=None) if issued_at else None,
            )
            self.session.add(timestamp_artifact)

        self.session.commit()
        self.session.refresh(document)
        self.session.refresh(signed_version)
        if timestamp_artifact:
            self.session.refresh(timestamp_artifact)

        return signed_version, timestamp_artifact, signature_result


    def sign_version_with_agent(
        self,
        document: Document,
        version: DocumentVersion,
        request: SignPdfRequest,
        user_id: str | UUID,
    ) -> tuple[DocumentVersion, dict[str, Any]]:
        import logging
        logger = logging.getLogger("nacionalsign.sign")
        logger.info(f"[sign_version_with_agent] Iniciando assinatura para documento={document.id}, version={version.id}")
        if version.document_id != document.id:
            logger.error("VersÃ£o nÃ£o pertence ao documento informado.")
            raise ValueError("VersÃ£o nÃ£o pertence ao documento informado.")
        if version.mime_type != "application/pdf":
            logger.error("A versÃ£o atual nÃ£o Ã© um PDF.")
            raise ValueError("A versÃ£o atual nÃ£o Ã© um PDF.")

        storage = get_storage()
        pdf_bytes = storage.load_bytes(version.storage_path)
        logger.info(f"[sign_version_with_agent] PDF original carregado de {version.storage_path} ({len(pdf_bytes)} bytes)")

        payload = build_sign_pdf_payload(
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

        client = SigningAgentClient()
        response = client.sign_pdf(payload)
        signed_pdf = decode_agent_pdf(response)
        logger.info(f"[sign_version_with_agent] PDF assinado recebido do agente ({len(signed_pdf)} bytes)")

        sha256_hash = hashlib.sha256(signed_pdf).hexdigest()
        storage_root = f"documents/{document.tenant_id}/{document.id}"
        signed_file_name = f"final-{sha256_hash}.pdf"

        logger.info(f"[sign_version_with_agent] Salvando PDF assinado em {storage_root}/{signed_file_name}")
        storage_path = storage.save_bytes(
            root=storage_root,
            name=signed_file_name,
            data=signed_pdf,
        )
        storage_path = normalize_storage_path(storage_path)
        logger.info(f"[sign_version_with_agent] PDF assinado salvo em {storage_path}")

        base_label = Path(version.original_filename or f"{document.id}.pdf").stem
        original_name = f"{base_label}-assinatura-final.pdf"

        signer_uuid = UUID(str(user_id))
        signed_version = DocumentVersion(
            document_id=document.id,
            storage_path=storage_path,
            original_filename=original_name,
            mime_type="application/pdf",
            size_bytes=len(signed_pdf),
            sha256=sha256_hash,
            uploaded_by_id=signer_uuid,
        )
        self.session.add(signed_version)
        logger.info(f"[sign_version_with_agent] Nova versÃ£o criada: {signed_version.id}")
        self.session.flush()

        document.current_version_id = signed_version.id
        document.status = DocumentStatus.COMPLETED
        self.session.add(document)

        logger.info(f"[sign_version_with_agent] Commitando transaÃ§Ã£o no banco de dados...")
        self.session.commit()
        self.session.refresh(document)
        self.session.refresh(signed_version)
        logger.info(f"[sign_version_with_agent] Processo finalizado com sucesso para documento={document.id}, version={signed_version.id}")

        return signed_version, response

    def list_fields(self, document: Document, version: DocumentVersion) -> list[DocumentField]:
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




