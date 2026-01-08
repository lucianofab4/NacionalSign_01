from __future__ import annotations
import base64
import binascii
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Iterable, Any, Dict, Tuple
from uuid import UUID
from fastapi import HTTPException
from sqlmodel import Session, select
from app.core.config import settings
from app.models.document import AuditArtifact, Document, DocumentGroup, DocumentParty, DocumentField, DocumentStatus
from app.models.customer import Customer
from app.models.user import User
from app.models.tenant import Area
from app.models.workflow import (
    Signature,
    SignatureRequest,
    SignatureRequestStatus,
    SignatureType,
    WorkflowInstance,
    WorkflowStatus,
    WorkflowStep,
    WorkflowTemplate,
)
from pydantic import ValidationError
from app.schemas.workflow import (
    SignatureAction,
    WorkflowDispatch,
    WorkflowStepConfig,
    WorkflowTemplateCreate,
    WorkflowTemplateUpdate,
)
from app.models.notification import UserNotification
from app.services.notification import NotificationService
from app.services.report import ReportService
from app.services.document import DocumentService
from app.services.audit import AuditService
from app.services.icp import SignatureResult
from app.services.storage import get_storage, normalize_storage_path

class WorkflowService:
    MAX_SIGNATURE_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MB
    ALLOWED_SIGNATURE_IMAGE_MIMES: Dict[str, str] = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
    }
    DEFAULT_SIGNATURE_IMAGE_EXT = ".png"
    _CERTIFICATE_CPF_PATTERNS = (
        re.compile(r"CPF\s*[:=]?\s*([0-9]{3}\.?[0-9]{3}\.?[0-9]{3}-?[0-9]{2})", re.IGNORECASE),
        re.compile(r"SERIALNUMBER\s*[:=]?\s*(?:CPF\s*)?([0-9]{3}\.?[0-9]{3}\.?[0-9]{3}-?[0-9]{2})", re.IGNORECASE),
        re.compile(r"2\.16\.76\.1\.3\.1\s*[:=]?\s*([0-9]{11})", re.IGNORECASE),
    )
    _GENERIC_CPF_PATTERN = re.compile(r"([0-9]{3}\.?[0-9]{3}\.?[0-9]{3}-?[0-9]{2})")

    def __init__(self, session: Session, notification_service: NotificationService | None = None) -> None:
        self.session = session
        self.notification_service = notification_service
        self.report_service = ReportService(session)

    def _resolve_company_name(self, tenant_id: UUID | None) -> str | None:
        if not tenant_id:
            return None
        try:
            tenant_uuid = UUID(str(tenant_id))
        except (TypeError, ValueError):
            return None
        customer = self.session.exec(select(Customer).where(Customer.tenant_id == tenant_uuid)).first()
        if customer:
            return customer.trade_name or customer.corporate_name
        return None

    @staticmethod
    def _normalize_cpf_value(value: str | None) -> str | None:
        if not value:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) != 11:
            return None
        return digits

    @classmethod
    def _extract_certificate_cpf(cls, *values: str | None) -> str | None:
        for raw in values:
            normalized = cls._extract_cpf_from_text(raw)
            if normalized:
                return normalized
        return None

    @classmethod
    def _extract_cpf_from_text(cls, raw: str | None) -> str | None:
        if not raw:
            return None
        text = raw.strip()
        if not text:
            return None
        for pattern in cls._CERTIFICATE_CPF_PATTERNS:
            match = pattern.search(text)
            if match:
                digits = "".join(ch for ch in match.group(1) if ch.isdigit())
                if len(digits) == 11:
                    return digits
        upper = text.upper()
        if any(keyword in upper for keyword in ("CPF", "SERIALNUMBER", "2.16.76.1.3.1")):
            generic = cls._GENERIC_CPF_PATTERN.search(text)
            if generic:
                digits = "".join(ch for ch in generic.group(1) if ch.isdigit())
                if len(digits) == 11:
                    return digits
        return None

    # Template management -------------------------------------------------
    def _prepare_template_config(self, steps: list[WorkflowStepConfig]) -> str:
        if not steps:
            raise ValueError("Template must contain at least one step")
        normalized: list[dict[str, object]] = []
        seen_orders: set[int] = set()
        for step in sorted(steps, key=lambda item: item.order):
            if step.order in seen_orders:
                raise ValueError("Template step orders must be unique")
            seen_orders.add(step.order)
            normalized.append(step.model_dump())
        return json.dumps(normalized)

    def create_template(
        self,
        tenant_id: UUID,
        area_id: UUID,
        payload: WorkflowTemplateCreate,
    ) -> WorkflowTemplate:
        area = self.session.get(Area, area_id)
        if not area or area.tenant_id != tenant_id:
            raise ValueError("Area not found for tenant")
        config_json = self._prepare_template_config(payload.steps)
        template = WorkflowTemplate(
            tenant_id=tenant_id,
            area_id=area_id,
            name=payload.name,
            description=payload.description,
            config_json=config_json,
        )
        self.session.add(template)
        self.session.commit()
        self.session.refresh(template)
        return template

    def list_templates(
        self,
        tenant_id: UUID,
        area_id: UUID | None = None,
        include_inactive: bool = False,
    ) -> list[WorkflowTemplate]:
        statement = select(WorkflowTemplate).where(WorkflowTemplate.tenant_id == tenant_id)
        if area_id:
            statement = statement.where(WorkflowTemplate.area_id == area_id)
        if not include_inactive:
            statement = statement.where(WorkflowTemplate.is_active.is_(True))
        return self.session.exec(statement).all()

    def get_template(self, template_id: UUID) -> WorkflowTemplate | None:
        return self.session.get(WorkflowTemplate, template_id)

    def update_template(
        self,
        tenant_id: UUID,
        template_id: UUID,
        payload: WorkflowTemplateUpdate,
    ) -> WorkflowTemplate:
        template = self.get_template(template_id)
        if not template or template.tenant_id != tenant_id:
            raise ValueError("Template not found for tenant")
        if payload.name is not None:
            template.name = payload.name
        if payload.description is not None:
            template.description = payload.description
        if payload.steps is not None:
            template.config_json = self._prepare_template_config(payload.steps)
        if payload.is_active is not None:
            template.is_active = payload.is_active
        self.session.add(template)
        self.session.commit()
        self.session.refresh(template)
        return template

    def deactivate_template(self, tenant_id: UUID, template_id: UUID) -> WorkflowTemplate:
        template = self.get_template(template_id)
        if not template or template.tenant_id != tenant_id:
            raise ValueError("Template not found for tenant")
        template.is_active = False
        self.session.add(template)
        self.session.commit()
        self.session.refresh(template)
        return template

    def duplicate_template(
        self,
        tenant_id: UUID,
        template_id: UUID,
        *,
        name: str,
        area_id: UUID | None = None,
    ) -> WorkflowTemplate:
        source = self.get_template(template_id)
        if not source or source.tenant_id != tenant_id:
            raise ValueError("Template not found for tenant")
        new_template = WorkflowTemplate(
            tenant_id=tenant_id,
            area_id=area_id or source.area_id,
            name=name,
            description=source.description,
            config_json=source.config_json,
        )
        self.session.add(new_template)
        self.session.commit()
        self.session.refresh(new_template)
        return new_template

    # Workflow execution ---------------------------------------------------
    def get_workflow(self, workflow_id: str | UUID) -> WorkflowInstance | None:
        return self.session.get(WorkflowInstance, UUID(str(workflow_id)))

    def list_workflows(self, document_id: str | UUID) -> Iterable[WorkflowInstance]:
        statement = select(WorkflowInstance).where(WorkflowInstance.document_id == UUID(str(document_id)))
        return self.session.exec(statement).all()

    def _get_document(self, tenant_id: UUID, document_id: UUID) -> Document:
        document = self.session.get(Document, document_id)
        if not document or document.tenant_id != tenant_id:
            raise ValueError("Document not found for tenant")
        return document

    def _load_template_steps(self, template: WorkflowTemplate) -> list[WorkflowStepConfig]:
        try:
            raw_config = json.loads(template.config_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid template configuration") from exc
        if not isinstance(raw_config, list):
            raise ValueError("Template configuration must be a list")
        steps: list[WorkflowStepConfig] = []
        for item in raw_config:
            if not isinstance(item, dict):
                raise ValueError("Malformed template step")
            try:
                steps.append(WorkflowStepConfig.model_validate(item))
            except ValidationError as exc:
                raise ValueError("Invalid template step configuration") from exc
        return sorted(steps, key=lambda cfg: cfg.order)

    def _match_template_parties(
        self,
        document_parties: list[DocumentParty],
        steps: list[WorkflowStepConfig],
    ) -> list[tuple[DocumentParty, WorkflowStepConfig]]:
        if not document_parties:
            raise ValueError("No parties configured for document")
        parties_by_role: dict[str, list[DocumentParty]] = {}
        for party in sorted(document_parties, key=lambda item: item.order_index):
            role_key = (party.role or "").strip().lower()
            parties_by_role.setdefault(role_key, []).append(party)
        usage: dict[str, int] = {}
        assignments: list[tuple[DocumentParty, WorkflowStepConfig]] = []
        for step in steps:
            role_key = step.role
            candidates = parties_by_role.get(role_key)
            if not candidates:
                raise ValueError(f"Template requires party with role '{role_key}'")
            index = usage.get(role_key, 0)
            if index >= len(candidates):
                raise ValueError(f"Template requires more parties with role '{role_key}' than configured")
            party = candidates[index]
            usage[role_key] = index + 1
            assignments.append((party, step))
        return assignments

    def _load_document_parties(self, document: Document) -> list[DocumentParty]:
        parties = self.session.exec(
            select(DocumentParty)
            .where(DocumentParty.document_id == document.id)
            .order_by(DocumentParty.order_index)
        ).all()
        if not parties:
            raise ValueError("No parties configured for document")
        return parties

    def _normalize_notification_channels(self, parties: list[DocumentParty]) -> dict[UUID, str]:
        contact_issues: list[str] = []
        normalized_channels: dict[UUID, str] = {}
        for party in parties:
            channel = (party.notification_channel or "email").lower()
            if channel not in {"email", "sms"}:
                channel = "email"
            normalized_channels[party.id] = channel
            if channel == "email" and not (party.email and party.email.strip()):
                contact_issues.append(f"{party.full_name or party.role or party.id}: e-mail obrigatorio.")
            if channel == "sms" and not (party.phone_number and party.phone_number.strip()):
                contact_issues.append(f"{party.full_name or party.role or party.id}: telefone obrigatorio para SMS.")
        if contact_issues:
            raise ValueError(f"Contatos pendentes antes do envio: {' '.join(contact_issues)}")
        return normalized_channels

    def _build_step_assignments(
        self,
        document: Document,
        parties: list[DocumentParty],
        payload: WorkflowDispatch,
    ) -> list[tuple[DocumentParty, WorkflowStepConfig]]:
        if payload.template_id and payload.steps:
            raise ValueError("Escolha entre usar um template ou definir o fluxo manualmente, nao ambos.")
        if payload.template_id:
            template = self.get_template(payload.template_id)
            if not template or template.tenant_id != document.tenant_id:
                raise ValueError("Template not found for tenant")
            config_steps = self._load_template_steps(template)
            return self._match_template_parties(parties, config_steps)
        if payload.steps:
            sorted_steps = sorted(payload.steps, key=lambda item: item.order)
            return self._match_template_parties(parties, sorted_steps)
        return [
            (
                party,
                WorkflowStepConfig(
                    order=index,
                    role=(party.role or "").strip().lower(),
                    action="sign",
                    execution="sequential",
                ),
            )
            for index, party in enumerate(parties, start=1)
        ]

    def _list_group_documents(self, group_id: UUID) -> list[Document]:
        return self.session.exec(
            select(Document)
            .where(Document.group_id == group_id)
            .order_by(Document.created_at.asc())
        ).all()

    def _clone_parties_to_document(
        self,
        *,
        source_parties: list[DocumentParty],
        target_document: Document,
    ) -> None:
        existing = self.session.exec(
            select(DocumentParty).where(DocumentParty.document_id == target_document.id)
        ).all()
        for party in existing:
            self.session.delete(party)
        self.session.flush()
        for source in source_parties:
            data = source.model_dump(exclude={"id", "created_at", "updated_at", "document_id"})
            data["document_id"] = target_document.id
            clone = DocumentParty(**data)
            self.session.add(clone)
        self.session.flush()

    def issue_signature_token(self, request_id: UUID) -> str:
        request = self.session.get(SignatureRequest, UUID(str(request_id)))
        if not request:
            raise ValueError("Request not found")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        request.token_hash = token_hash
        request.token_expires_at = None
        if not request.token_channel:
            request.token_channel = "email"
        self.session.add(request)
        self.session.flush()
        return token

    def _find_request_by_token(self, token: str) -> SignatureRequest:
        normalized_token = (token or "").strip()
        if not normalized_token:
            raise ValueError("Invalid token")
        token_hash = hashlib.sha256(normalized_token.encode()).hexdigest()
        request = self.session.exec(
            select(SignatureRequest).where(SignatureRequest.token_hash == token_hash)
        ).first()
        if not request:
            raise ValueError("Invalid token")
        expires_at = request.token_expires_at
        if expires_at:
            now = datetime.utcnow()
            if expires_at <= now:
                grace_hours = max(int(settings.public_token_grace_hours or 0), 0)
                grace_limit = expires_at + timedelta(hours=grace_hours) if grace_hours > 0 else expires_at
                if grace_limit <= now:
                    raise ValueError("Token expired")
                ttl_hours = max(int(settings.public_token_ttl_hours or 24), 1)
                request.token_expires_at = now + timedelta(hours=ttl_hours)
                self.session.add(request)
                self.session.flush()
        return request

    def dispatch_workflow(
        self,
        tenant_id: str | UUID,
        document_id: str | UUID,
        payload: WorkflowDispatch,
    ) -> WorkflowInstance:
        tenant_uuid = UUID(str(tenant_id))
        document_uuid = UUID(str(document_id))
        document = self._get_document(tenant_uuid, document_uuid)
        if document.status == DocumentStatus.DELETED:
            raise ValueError("Documento está na lixeira e não pode iniciar workflow")
        if document.status not in {DocumentStatus.IN_REVIEW, DocumentStatus.DRAFT}:
            raise ValueError("Document already in workflow")
        party_rows = self._load_document_parties(document)
        normalized_channels = self._normalize_notification_channels(party_rows)
        parties = self._build_step_assignments(document, party_rows, payload)
        workflow = WorkflowInstance(
            document_id=document.id,
            group_id=document.group_id,
            template_id=payload.template_id,
            status=WorkflowStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
        )
        self.session.add(workflow)
        self.session.flush()
        for index, (party, cfg) in enumerate(parties, start=1):
            deadline_at = None
            if cfg.deadline_hours:
                deadline_at = datetime.utcnow() + timedelta(hours=cfg.deadline_hours)
            phase_index = getattr(cfg, "order", None) or index
            step = WorkflowStep(
                workflow_id=workflow.id,
                party_id=party.id,
                step_index=index,
                phase_index=phase_index,
                action=cfg.action,
                execution_type=cfg.execution,
                deadline_at=deadline_at,
            )
            self.session.add(step)
            self.session.flush()
            channel = normalized_channels.get(party.id, "email")
            request = SignatureRequest(
                workflow_step_id=step.id,
                document_id=document.id,
                group_id=document.group_id,
                token_channel=channel,
                status=SignatureRequestStatus.PENDING,
            )
            self.session.add(request)
        document.status = DocumentStatus.IN_PROGRESS
        self._advance_workflow(workflow, document)
        self.session.add(document)
        self.session.commit()
        self.session.refresh(workflow)
        return workflow

    def dispatch_group_workflow(
        self,
        tenant_id: str | UUID,
        group_id: str | UUID,
        payload: WorkflowDispatch,
    ) -> tuple[DocumentGroup, list[WorkflowInstance]]:
        tenant_uuid = UUID(str(tenant_id))
        group = self.session.get(DocumentGroup, UUID(str(group_id)))
        if not group or group.tenant_id != tenant_uuid:
            raise ValueError("Grupo nao encontrado para o tenant.")
        documents = self._list_group_documents(group.id)
        if not documents:
            raise ValueError("O grupo nao possui documentos para iniciar o fluxo.")
        deleted = [doc for doc in documents if doc.status == DocumentStatus.DELETED]
        if deleted:
            names = ", ".join(doc.name for doc in deleted)
            raise ValueError(f"Documentos na lixeira não podem iniciar workflow: {names}")
        invalid = [doc for doc in documents if doc.status not in {DocumentStatus.IN_REVIEW, DocumentStatus.DRAFT}]
        if invalid:
            names = ", ".join(doc.name for doc in invalid)
            raise ValueError(f"Os seguintes documentos nao podem iniciar o fluxo: {names}.")
        primary_document = documents[0]
        party_rows = self._load_document_parties(primary_document)
        normalized_channels = self._normalize_notification_channels(party_rows)
        parties = self._build_step_assignments(primary_document, party_rows, payload)
        for document in documents:
            if document.id == primary_document.id:
                continue
            self._clone_parties_to_document(source_parties=party_rows, target_document=document)
        workflow = WorkflowInstance(
            document_id=primary_document.id,
            group_id=group.id,
            template_id=payload.template_id,
            status=WorkflowStatus.IN_PROGRESS,
            started_at=datetime.utcnow(),
            is_group_workflow=True,
        )
        self.session.add(workflow)
        self.session.flush()
        for index, (party, cfg) in enumerate(parties, start=1):
            deadline_at = None
            if cfg.deadline_hours:
                deadline_at = datetime.utcnow() + timedelta(hours=cfg.deadline_hours)
            phase_index = getattr(cfg, "order", None) or index
            step = WorkflowStep(
                workflow_id=workflow.id,
                party_id=party.id,
                step_index=index,
                phase_index=phase_index,
                action=cfg.action,
                execution_type=cfg.execution,
                deadline_at=deadline_at,
            )
            self.session.add(step)
            self.session.flush()
            for document in documents:
                channel = normalized_channels.get(party.id, "email")
                request = SignatureRequest(
                    workflow_step_id=step.id,
                    document_id=document.id,
                    group_id=group.id,
                    token_channel=channel,
                    status=SignatureRequestStatus.PENDING,
                )
                self.session.add(request)
        for document in documents:
            document.status = DocumentStatus.IN_PROGRESS
            self.session.add(document)
        self._advance_workflow(workflow, primary_document)
        self.session.commit()
        self.session.refresh(group)
        self.session.refresh(workflow)
        return group, [workflow]

    def _apply_signature_action(
        self,
        request: SignatureRequest,
        workflow: WorkflowInstance,
        document: Document,
        payload: SignatureAction,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> SignatureRequest:
        if request.status not in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT}:
            raise ValueError("Request already closed")
        step = self.session.get(WorkflowStep, request.workflow_step_id)
        if not step:
            raise ValueError("Workflow step missing")
        party = step.party or self.session.get(DocumentParty, step.party_id)
        now = datetime.utcnow()
        signature_entry: Signature | None = None
        evidence_log: Dict[str, Any] | None = None
        if payload.action == "sign":
            field_meta = self._collect_field_metadata(document, party)
            typed_required = field_meta["typed_name_required"]
            image_required = field_meta["signature_image_required"]
            available_fields = field_meta["field_types"]
            role_fields = self._load_role_fields(document, party)
            field_lookup: Dict[str, DocumentField] = {str(field.id): field for field in role_fields}
            required_field_ids = {
                str(field.id)
                for field in role_fields
                if field.field_type in {"signature", "signature_image", "typed_name"} and field.required
            }
            provided_field_ids: set[str] = set()
            field_value_capture: Dict[str, Dict[str, Any]] = {}
            if typed_required and party and not party.allow_typed_name:
                raise ValueError("Configuração do signatário não permite nome digitado obrigatório.")
            if image_required and party and not party.allow_signature_image:
                raise ValueError("Configuração do signatário não permite imagem obrigatória.")
            if request.token_hash and payload.token:
                signature_type_label = (payload.signature_type or "").strip().lower()
                method = (getattr(party, "signature_method", "") or "").strip().lower()
                is_digital = (
                    signature_type_label == "digital"
                    or "digital" in signature_type_label
                    or "icp" in signature_type_label
                    or method in {
                        "digital",
                        "certificado",
                        "certificado digital",
                        "certificado-icp",
                        "icp",
                        "icp-brasil",
                    }
                )
                if is_digital:
                    pass
                else:
                    if party and party.require_email and getattr(party, "email", None):
                        expected_email = party.email.strip().lower()
                        provided_email = (payload.confirm_email or "").strip().lower()
                        if not provided_email or expected_email != provided_email:
                            raise ValueError("Confirme o e-mail cadastrado para continuar.")
                    if party and party.require_phone and getattr(party, "phone_number", None):
                        digits = "".join(ch for ch in party.phone_number if ch.isdigit())
                        expected_target = digits[-4:] if len(digits) > 4 else digits
                        provided_last4 = "".join(ch for ch in (payload.confirm_phone_last4 or "") if ch.isdigit())
                        if expected_target:
                            if not provided_last4 or provided_last4 != expected_target:
                                message = (
                                    "Informe os últimos 4 dígitos do telefone cadastrado."
                                    if len(expected_target) >= 4
                                    else "Informe o telefone cadastrado utilizando apenas números."
                                )
                                raise ValueError(message)
            typed_name_value = payload.typed_name.strip() if payload.typed_name else None
            if typed_name_value:
                if party and not party.allow_typed_name:
                    raise ValueError("Nome digitado não é permitido para este signatário.")
                if len(typed_name_value) < 3:
                    raise ValueError("Nome digitado deve ter pelo menos 3 caracteres.")
                typed_name_hash = hashlib.sha256(typed_name_value.encode("utf-8")).hexdigest()
            else:
                typed_name_hash = None
                if typed_required:
                    raise ValueError("O nome digitado é obrigatório para esta assinatura.")
            consent_given = bool(payload.consent)
            consent_text = payload.consent_text.strip() if payload.consent_text else None
            if consent_text and len(consent_text) > 2000:
                consent_text = consent_text[:2000]
            consent_version = payload.consent_version.strip() if payload.consent_version else None
            consent_given_at = now if consent_given else None
            document_service = DocumentService(self.session)
            if payload.fields:
                for field_payload in payload.fields:
                    field_id = str(getattr(field_payload, "field_id", "")).strip()
                    if not field_id:
                        continue
                    field_obj = field_lookup.get(field_id)
                    if not field_obj:
                        continue
                    if field_obj.field_type not in {"signature", "signature_image", "typed_name"}:
                        continue
                    normalized = document_service.apply_field_signature(
                        document=document,
                        field=field_obj,
                        payload=field_payload.model_dump(exclude_unset=True),
                    )
                    if normalized:
                        provided_field_ids.add(field_id)
                        field_value_capture[field_id] = normalized
            if typed_name_value:
                for field in role_fields:
                    field_key = str(field.id)
                    if field.field_type != "typed_name" or field_key in provided_field_ids:
                        continue
                    normalized = document_service.apply_field_signature(
                        document=document,
                        field=field,
                        payload={"typed_name": typed_name_value},
                    )
                    if normalized:
                        provided_field_ids.add(field_key)
                        field_value_capture[field_key] = normalized
                    break
            top_signature_payload: dict[str, Any] | None = None
            if payload.signature_image:
                top_signature_payload = {
                    "signature_image": payload.signature_image,
                    "signature_image_mime": payload.signature_image_mime,
                    "signature_image_name": payload.signature_image_name,
                }
                for field in role_fields:
                    field_key = str(field.id)
                    if field.field_type != "signature_image" or field_key in provided_field_ids:
                        continue
                    normalized = document_service.apply_field_signature(
                        document=document,
                        field=field,
                        payload={k: v for k, v in top_signature_payload.items() if v},
                    )
                    if normalized:
                        provided_field_ids.add(field_key)
                        field_value_capture[field_key] = normalized
                    break
            if required_field_ids:
                missing_required = [
                    field_lookup[field_id].label or field_lookup[field_id].field_type
                    for field_id in required_field_ids
                    if field_id not in provided_field_ids
                ]
                if missing_required:
                    targets = ", ".join(missing_required)
                    raise ValueError(f"Preencha os campos obrigatórios: {targets}")
            image_payload = payload.signature_image
            image_meta: Dict[str, Any] | None = None
            if image_payload:
                if party and not party.allow_signature_image:
                    raise ValueError("Upload de imagem não é permitido para este signatário.")
                image_bytes, detected_mime = self._decode_signature_image(image_payload)
                image_mime = (payload.signature_image_mime or detected_mime or "image/png").lower()
                if image_mime not in self.ALLOWED_SIGNATURE_IMAGE_MIMES:
                    raise ValueError("Formato de imagem não suportado. Utilize PNG ou JPEG.")
                if not image_bytes:
                    raise ValueError("Imagem de assinatura vazia.")
                if len(image_bytes) > self.MAX_SIGNATURE_IMAGE_BYTES:
                    raise ValueError("Imagem de assinatura excede o limite de 2 MB.")
                if not consent_given:
                    raise ValueError("É necessário autorizar o uso da imagem para concluir a assinatura.")
                extension = self.ALLOWED_SIGNATURE_IMAGE_MIMES[image_mime]
                filename = self._build_signature_filename(payload.signature_image_name, extension, request.id)
                storage = get_storage()
                storage_root = f"signatures/{document.tenant_id}/{document.id}"
                storage_path = storage.save_bytes(
                    root=storage_root,
                    name=filename,
                    data=image_bytes,
                )
                storage_path = normalize_storage_path(storage_path)
                image_sha = hashlib.sha256(image_bytes).hexdigest()
                artifact = AuditArtifact(
                    document_id=document.id,
                    artifact_type="signature_image",
                    storage_path=storage_path,
                    sha256=image_sha,
                    issued_at=now,
                )
                self.session.add(artifact)
                self.session.flush()
                image_meta = {
                    "mime": image_mime,
                    "size": len(image_bytes),
                    "sha256": image_sha,
                    "filename": filename,
                    "artifact_id": artifact.id,
                    "path": storage_path,
                }
            elif image_required:
                raise ValueError("Imagem de assinatura é obrigatória para este signatário.")
            certificate_subject = (payload.certificate_subject or "").strip() or None
            certificate_issuer = (payload.certificate_issuer or "").strip() or None
            certificate_serial = (payload.certificate_serial or "").strip() or None
            certificate_thumbprint = (payload.certificate_thumbprint or "").strip() or None
            signature_protocol = (payload.signature_protocol or "").strip() or None
            signature_type_label = (payload.signature_type or "").strip() or None
            signature_authentication = (payload.signature_authentication or "").strip() or None
            signed_pdf_raw = payload.signed_pdf or None
            signed_pdf_meta: Dict[str, Any] | None = None
            if signed_pdf_raw:
                try:
                    signed_pdf_bytes = base64.b64decode(signed_pdf_raw, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("PDF assinado em formato inválido.") from exc
                if not signed_pdf_bytes:
                    raise ValueError("PDF assinado está vazio.")
                storage = get_storage()
                storage_root = f"signatures/{document.tenant_id}/{document.id}"
                signed_filename = (payload.signed_pdf_name or f"assinatura-digital-{request.id}.pdf").strip() or f"assinatura-digital-{request.id}.pdf"
                signed_filename = signed_filename.replace("\\", "_").replace("/", "_")
                signed_mime = (payload.signed_pdf_mime or "application/pdf").strip() or "application/pdf"
                storage_path = storage.save_bytes(
                    root=storage_root,
                    name=signed_filename,
                    data=signed_pdf_bytes,
                )
                storage_path = normalize_storage_path(storage_path)
                signed_sha = (payload.signed_pdf_digest or "").strip() or hashlib.sha256(signed_pdf_bytes).hexdigest()
                artifact = AuditArtifact(
                    document_id=document.id,
                    artifact_type="signature_pdf",
                    storage_path=storage_path,
                    sha256=signed_sha,
                    issued_at=now,
                )
                self.session.add(artifact)
                self.session.flush()
                signed_pdf_meta = {
                    "mime": signed_mime,
                    "size": len(signed_pdf_bytes),
                    "sha256": signed_sha,
                    "filename": signed_filename,
                    "artifact_id": artifact.id,
                    "path": storage_path,
                }
            signature_type_indicates_certificate = bool(
                signature_type_label
                and any(marker in signature_type_label for marker in ("digital", "certificado", "icp"))
            )
            signature_auth_value = (signature_authentication or "").strip().lower()
            signature_auth_indicates_certificate = bool(
                signature_auth_value and any(marker in signature_auth_value for marker in ("digital", "certificado", "icp"))
            )
            certificate_used = any(
                [
                    certificate_subject,
                    certificate_issuer,
                    certificate_serial,
                    certificate_thumbprint,
                    signature_type_indicates_certificate,
                    signature_auth_indicates_certificate,
                    signed_pdf_meta,
                ]
            )
            certificate_cpf = (
                self._extract_certificate_cpf(
                    certificate_subject,
                    certificate_issuer,
                    certificate_serial,
                    certificate_thumbprint,
                    signature_protocol,
                    signature_type_label,
                    signature_authentication,
                )
                if certificate_used
                else None
            )
            evidence_options: Dict[str, Any] = {
                "typed_name": bool(typed_name_value),
                "signature_image": bool(image_payload),
                "signature_draw": False,
            }
            if available_fields:
                evidence_options["available_fields"] = available_fields
            if certificate_used:
                certificate_payload = {
                    "subject": certificate_subject,
                    "issuer": certificate_issuer,
                    "serial": certificate_serial,
                    "thumbprint": certificate_thumbprint,
                }
                if certificate_cpf:
                    certificate_payload["cpf"] = certificate_cpf
                evidence_options["certificate"] = certificate_payload
            if signature_protocol:
                evidence_options["signature_protocol"] = signature_protocol
            if signature_type_label:
                evidence_options["signature_type_label"] = signature_type_label
            if signature_authentication:
                evidence_options["signature_authentication"] = signature_authentication
            if signed_pdf_meta:
                evidence_options["signed_pdf_artifact_id"] = str(signed_pdf_meta["artifact_id"])
                evidence_options["signed_pdf_sha256"] = signed_pdf_meta["sha256"]
            signature_method = (
                getattr(party, "signature_method", None).strip().lower()
                if party and getattr(party, "signature_method", None)
                else "electronic"
            )
            normalized_party_cpf = self._normalize_cpf_value(getattr(party, "cpf", None)) if party else None
            confirmed_cpf = self._normalize_cpf_value(payload.confirm_cpf)
            if signature_method == "digital":
                if not certificate_used:
                    raise ValueError("Esta assinatura exige uso de certificado digital.")
                if not normalized_party_cpf:
                    raise ValueError("CPF do participante é obrigatório para assinaturas com certificado digital.")
                if certificate_cpf:
                    if certificate_cpf != normalized_party_cpf:
                        raise ValueError("O CPF do certificado digital não corresponde ao participante cadastrado.")
                else:
                    if not confirmed_cpf:
                        raise ValueError("Confirme o CPF cadastrado para continuar.")
                    if confirmed_cpf != normalized_party_cpf:
                        raise ValueError("O CPF informado não corresponde ao participante cadastrado.")
            if signature_method == "electronic" and certificate_used:
                raise ValueError("Esta assinatura deve ser realizada de forma eletrônica.")
            signature_entry = Signature(
                signature_request_id=request.id,
                signature_type=SignatureType.DIGITAL if certificate_used else SignatureType.ELECTRONIC,
                signed_at=now,
                signer_ip=ip,
                signer_user_agent=user_agent,
                reason=payload.reason,
                typed_name=typed_name_value,
                typed_name_hash=typed_name_hash,
                field_values=field_value_capture or None,
                evidence_options=evidence_options,
                consent_given=consent_given,
                consent_text=consent_text,
                consent_version=consent_version,
                consent_given_at=consent_given_at,
                digest_sha256=signed_pdf_meta["sha256"] if signed_pdf_meta else None,
                certificate_serial=certificate_serial,
                evidence_image_artifact_id=image_meta.get("artifact_id") if image_meta else None,
                evidence_image_mime_type=image_meta.get("mime") if image_meta else None,
                evidence_image_size=image_meta.get("size") if image_meta else None,
                evidence_image_sha256=image_meta.get("sha256") if image_meta else None,
                evidence_image_filename=image_meta.get("filename") if image_meta else None,
            )
            self.session.add(signature_entry)
            self.session.flush()
            self._record_party_signed_notification(
                document=document,
                party=party,
                signature=signature_entry,
            )
            evidence_log = {
                "signature_id": str(signature_entry.id),
                "request_id": str(request.id),
                "options": evidence_options,
            }
            if typed_name_value:
                evidence_log["typed_name"] = typed_name_value
                evidence_log["typed_name_hash"] = typed_name_hash
            if image_meta:
                evidence_log["image_artifact_id"] = str(image_meta["artifact_id"])
                evidence_log["image_sha256"] = image_meta["sha256"]
                evidence_log["image_mime_type"] = image_meta["mime"]
                evidence_log["image_size_bytes"] = image_meta["size"]
                evidence_log["image_filename"] = image_meta["filename"]
                evidence_log["image_storage_path"] = image_meta["path"]
            if certificate_used:
                evidence_log["certificate_subject"] = certificate_subject
                evidence_log["certificate_issuer"] = certificate_issuer
                evidence_log["certificate_serial"] = certificate_serial
                evidence_log["certificate_thumbprint"] = certificate_thumbprint
                if certificate_cpf:
                    evidence_log["certificate_cpf"] = certificate_cpf
                if signature_protocol:
                    evidence_log["signature_protocol"] = signature_protocol
                if signature_type_label:
                    evidence_log["signature_type_label"] = signature_type_label
                if signature_authentication:
                    evidence_log["signature_authentication"] = signature_authentication
            if signed_pdf_meta:
                evidence_log["signed_pdf_artifact_id"] = str(signed_pdf_meta["artifact_id"])
                evidence_log["signed_pdf_sha256"] = signed_pdf_meta["sha256"]
                evidence_log["signed_pdf_filename"] = signed_pdf_meta["filename"]
                evidence_log["signed_pdf_size_bytes"] = signed_pdf_meta["size"]
                evidence_log["signed_pdf_mime_type"] = signed_pdf_meta["mime"]
                evidence_log["signed_pdf_storage_path"] = signed_pdf_meta["path"]
            if consent_given:
                evidence_log["consent_version"] = consent_version
                if consent_text:
                    evidence_log["consent_text"] = consent_text
                if consent_given_at:
                    evidence_log["consent_given_at"] = consent_given_at.isoformat()
            if field_value_capture:
                evidence_log["field_signatures"] = list(field_value_capture.keys())
            request.status = SignatureRequestStatus.SIGNED
            step.completed_at = now
        elif payload.action == "refuse":
            request.status = SignatureRequestStatus.REFUSED
            signature_entry = Signature(
                signature_request_id=request.id,
                signature_type=SignatureType.ELECTRONIC,
                signed_at=now,
                signer_ip=ip,
                signer_user_agent=user_agent,
                reason=payload.reason,
            )
            workflow.status = WorkflowStatus.REJECTED
            workflow.completed_at = now
            document.status = DocumentStatus.REJECTED
            self.session.add(signature_entry)
            step.completed_at = now
        else:
            raise ValueError("Unknown action")
        request.token_expires_at = None
        self.session.add(request)
        self._advance_workflow(workflow, document)
        self.session.commit()
        self.session.refresh(request)
        self.session.refresh(workflow)
        self.session.refresh(document)
        if evidence_log:
            audit_service = AuditService(self.session)
            audit_service.record_event(
                event_type="signature_evidence_captured",
                actor_id=None,
                actor_role=None,
                document_id=document.id,
                ip_address=ip,
                user_agent=user_agent,
                details={key: value for key, value in evidence_log.items() if value is not None},
            )
        if workflow.status == WorkflowStatus.COMPLETED and document.status == DocumentStatus.COMPLETED:
            document_service = DocumentService(self.session)
            audit_service = AuditService(self.session)
            signature_result: SignatureResult | None = None
            try:
                final_version, _, signature_result = document_service.ensure_final_signed_version(document)
            except Exception as exc:
                print(f"[ERRO] Falha ao gerar versão final: {exc}")
                audit_service.record_event(
                    event_type="document_sign_error",
                    actor_id=None,
                    actor_role=None,
                    document_id=document.id,
                    details={"error": str(exc)},
                )
            else:
                self.session.refresh(document)
                if signature_result:
                    issued_at = (
                        signature_result.timestamp.issued_at.isoformat()
                        if signature_result.timestamp and signature_result.timestamp.issued_at
                        else None
                    )
                    authority = (
                        signature_result.timestamp.authority if signature_result.timestamp else None
                    )
                    audit_service.record_event(
                        event_type="document_signed",
                        actor_id=None,
                        actor_role=None,
                        document_id=document.id,
                        details={
                            "version_id": str(final_version.id),
                            "sha256": final_version.sha256,
                            "authority": authority,
                            "issued_at": issued_at,
                        },
                    )
                    for warning in signature_result.warnings:
                        audit_service.record_event(
                            event_type="icp_warning",
                            actor_id=None,
                            actor_role=None,
                            document_id=document.id,
                            details={"warning": warning},
                        )
            existing_artifact = self.session.exec(
                select(AuditArtifact)
                .where(AuditArtifact.document_id == document.id)
                .where(AuditArtifact.artifact_type == "final_report")
            ).first()
            report_artifact = existing_artifact
            extra_artifacts: list[AuditArtifact] = []
            if not report_artifact:
                report_service = ReportService(self.session)
                report_artifact, extra_artifacts = report_service.generate_final_report(document, workflow)
            else:
                extra_artifacts = self.session.exec(
                    select(AuditArtifact)
                    .where(AuditArtifact.document_id == document.id)
                    .where(AuditArtifact.artifact_type.like("final_report%"))
                    .where(AuditArtifact.id != report_artifact.id)
                ).all()
            if self.notification_service and report_artifact:
                parties = document_service.list_parties(document)
                attachments = [final_version.storage_path, report_artifact.storage_path]
                attachments.extend(extra.storage_path for extra in extra_artifacts)
                attachments = list(dict.fromkeys(attachments))
                extra_emails = []
                creator_email = getattr(document.created_by, "email", None)
                if creator_email:
                    extra_emails.append(creator_email)
                self.notification_service.notify_workflow_completed(
                    document=document,
                    parties=parties,
                    attachments=attachments,
                    extra_recipients=extra_emails or None,
                )
        return request

    def record_signature_action(
        self,
        tenant_id: str | UUID,
        request_id: str | UUID,
        payload: SignatureAction,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> SignatureRequest:
        request = self.session.get(SignatureRequest, UUID(str(request_id)))
        if not request:
            raise ValueError("Request not found")
        step = self.session.get(WorkflowStep, request.workflow_step_id)
        if not step:
            raise ValueError("Workflow step missing")
        workflow = self.session.get(WorkflowInstance, step.workflow_id)
        if not workflow:
            raise ValueError("Workflow missing")
        document = self.session.get(Document, workflow.document_id)
        if not document or document.tenant_id != UUID(str(tenant_id)):
            raise ValueError("Invalid tenant")
        return self._apply_signature_action(
            request,
            workflow,
            document,
            payload,
            ip=ip,
            user_agent=user_agent,
        )

    def _record_party_signed_notification(
        self,
        *,
        document: Document,
        party: DocumentParty | None,
        signature: Signature | None,
    ) -> None:
        recipient_id = getattr(document, "created_by_id", None)
        if not recipient_id:
            return
        payload = {
            "document_name": document.name,
            "signer_name": getattr(party, "full_name", None),
            "signer_email": getattr(party, "email", None),
            "signer_role": getattr(party, "role", None),
            "signed_at": signature.signed_at.isoformat() if signature and signature.signed_at else None,
            "signature_type": signature.signature_type.value if signature else None,
        }
        notification = UserNotification(
            tenant_id=document.tenant_id,
            document_id=document.id,
            recipient_id=recipient_id,
            party_id=party.id if party else None,
            event_type="document_party_signed",
            payload=payload,
        )
        self.session.add(notification)

    def _advance_workflow(self, workflow: WorkflowInstance, document: Document) -> None:
        steps = self.session.exec(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.step_index)
        ).all()
        if workflow.status == WorkflowStatus.REJECTED:
            self.session.add(workflow)
            return
        if all(step.completed_at for step in steps):
            workflow.status = WorkflowStatus.COMPLETED
            workflow.completed_at = datetime.utcnow()
            document.status = DocumentStatus.COMPLETED
            self.session.add(workflow)
            self.session.add(document)
            return
        now = datetime.utcnow()
        for step in steps:
            if step.completed_at:
                continue
            requests = self.session.exec(
                select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
            ).all()
            for request in requests:
                if request.status == SignatureRequestStatus.PENDING:
                    request.status = SignatureRequestStatus.SENT
                    token = self.issue_signature_token(request.id)
                    self.session.add(request)
                    if self.notification_service and (step.party or step.party_id):
                        party = step.party or self.session.get(DocumentParty, step.party_id)
                        if party:
                            request_doc = self.session.get(Document, request.document_id)
                            requester_name = self._resolve_company_name(getattr(request_doc, "tenant_id", None)) if request_doc else None
                            self.notification_service.notify_signature_request(
                                request=request,
                                party=party,
                                document=request_doc,
                                token=token,
                                step=step,
                                requester_name=requester_name,
                            )
            break

    def get_request_workflow(self, request: SignatureRequest) -> WorkflowInstance | None:
        step = self.session.get(WorkflowStep, request.workflow_step_id)
        if not step:
            return None
        return self.session.get(WorkflowInstance, step.workflow_id)

    def resend_pending_notifications(self, tenant_id: str | UUID, document_id: str | UUID) -> int:
        tenant_uuid = UUID(str(tenant_id))
        document_uuid = UUID(str(document_id))
        document = self._get_document(tenant_uuid, document_uuid)
        if document.status == DocumentStatus.DELETED:
            raise ValueError("Documento está na lixeira e não pode receber notificações")
        workflow = (
            self.session.exec(
                select(WorkflowInstance)
                .where(WorkflowInstance.document_id == document.id)
                .order_by(WorkflowInstance.created_at.desc())
            ).first()
        )
        if not workflow:
            raise ValueError("Workflow not found for document")
        steps = self.session.exec(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.step_index)
        ).all()
        if not steps:
            raise ValueError("No workflow steps to resend")
        if not self.notification_service:
            raise ValueError("Notification service is not configured")
        notified = 0
        for step in steps:
            requests = self.session.exec(
                select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)
            ).all()
            for request in requests:
                if request.status in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT}:
                    token = self.issue_signature_token(request.id)
                    request.status = SignatureRequestStatus.SENT
                    self.session.add(request)
                    party = step.party or self.session.get(DocumentParty, step.party_id)
                    if party:
                        request_doc = self.session.get(Document, request.document_id)
                        requester_name = self._resolve_company_name(getattr(request_doc, "tenant_id", None)) if request_doc else None
                        self.notification_service.notify_signature_request(
                            request=request,
                            party=party,
                            document=request_doc,
                            token=token,
                            step=step,
                            requester_name=requester_name,
                        )
                        notified += 1
        self.session.commit()
        return notified

    @staticmethod
    def _normalize_role(role: str | None) -> str:
        return (role or "").strip().lower()

    def _load_role_fields(self, document: Document, party: DocumentParty | None) -> list[DocumentField]:
        role = self._normalize_role(getattr(party, "role", None))
        if not role:
            return []
        document_service = DocumentService(self.session)
        version_id = document_service.resolve_field_version_id(document, document.current_version_id, role=role)
        if not version_id:
            return []
        statement = (
            select(DocumentField)
            .where(DocumentField.document_id == document.id)
            .where(DocumentField.version_id == version_id)
            .where(DocumentField.role == role)
            .order_by(DocumentField.page, DocumentField.created_at)
        )
        return self.session.exec(statement).all()

    def _collect_field_metadata(self, document: Document, party: DocumentParty | None) -> Dict[str, Any]:
        role = self._normalize_role(getattr(party, "role", None))
        if not role:
            return {
                "typed_name_required": False,
                "signature_image_required": False,
                "field_types": [],
            }
        fields = self.session.exec(
            select(DocumentField)
            .where(DocumentField.document_id == document.id)
            .where(DocumentField.role == role)
        ).all()
        typed_required = any(field.field_type == "typed_name" and field.required for field in fields)
        image_required = any(field.field_type == "signature_image" and field.required for field in fields)
        field_types = [field.field_type for field in fields]
        return {
            "typed_name_required": typed_required,
            "signature_image_required": image_required,
            "field_types": field_types,
        }

    @classmethod
    def _decode_signature_image(cls, payload: str) -> Tuple[bytes, str | None]:
        data = (payload or "").strip()
        if not data:
            raise ValueError("Imagem de assinatura inválida.")
        mime: str | None = None
        encoded = data
        if data.startswith("data:"):
            try:
                header, encoded = data.split(",", 1)
            except ValueError as exc:
                raise ValueError("Imagem de assinatura em formato inválido.") from exc
            if ";base64" not in header:
                raise ValueError("Imagem de assinatura deve estar codificada em base64.")
            if ":" in header:
                mime = header.split(";", 1)[0].split(":", 1)[1]
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Imagem de assinatura inválida.") from exc
        return content, mime

    @classmethod
    def _build_signature_filename(cls, provided: str | None, extension: str, request_id: UUID) -> str:
        base = (provided or f"assinatura-{request_id}").strip()
        if not base:
            base = f"assinatura-{request_id}"
        base = base.replace("\\", "_").replace("/", "_")
        if "." not in base:
            base = f"{base}{extension}"
        return base

    def get_public_signature(self, token: str) -> dict[str, object]:
        request = self._find_request_by_token(token)
        step = self.session.get(WorkflowStep, request.workflow_step_id)
        if not step:
            raise ValueError("Workflow step missing")
        workflow = self.session.get(WorkflowInstance, step.workflow_id)
        if not workflow:
            raise ValueError("Workflow missing")
        document = self.session.get(Document, request.document_id)
        if not document:
            raise ValueError("Document missing")
        if document.status == DocumentStatus.DELETED:
            raise ValueError("Documento está na lixeira e não pode ser assinado")
        self.session.refresh(document)
        party = step.party or self.session.get(DocumentParty, step.party_id)
        signature = self.session.exec(
            select(Signature)
            .where(Signature.signature_request_id == request.id)
            .order_by(Signature.created_at.desc())
        ).first()
        return {
            "document": document,
            "workflow": workflow,
            "party": party,
            "request": request,
            "signature": signature,
        }

    def record_public_signature_action(
        self,
        token: str,
        payload: SignatureAction,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> SignatureRequest:
        request = self._find_request_by_token(token)
        step = self.session.get(WorkflowStep, request.workflow_step_id)
        if not step:
            raise ValueError("Workflow step missing")
        workflow = self.session.get(WorkflowInstance, step.workflow_id)
        if not workflow:
            raise ValueError("Workflow missing")
        document = self.session.get(Document, workflow.document_id)
        if not document:
            raise ValueError("Document missing")
        if document.status == DocumentStatus.DELETED:
            raise ValueError("Documento está na lixeira e não pode ser assinado")
        return self._apply_signature_action(
            request,
            workflow,
            document,
            payload,
            ip=ip,
            user_agent=user_agent,
        )
