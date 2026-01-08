from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_db
from app.core.config import settings
from app.models.document import Document, DocumentGroup, DocumentParty, DocumentVersion, DocumentField
from app.models.signing import SigningAgentAttempt, SigningAgentAttemptStatus
from app.models.workflow import SignatureRequest, SignatureRequestStatus, WorkflowInstance, WorkflowStep
from app.schemas.document import DocumentFieldRead
from app.schemas.signing_agent import (
    PublicAgentSessionCompletePayload,
    PublicAgentSessionStartPayload,
    PublicAgentSessionStartResponse,
    SigningCertificate,
    SignPdfRequest,
    SignPdfResponse,
)
from app.schemas.workflow import SignatureAction
from app.schemas.public import PublicSignatureRead, PublicGroupDocument
from app.services.audit import AuditService
from app.services.document import DocumentService
from app.services.notification import NotificationService
from app.services.signing_agent import SigningAgentError
from app.services.workflow import WorkflowService

router = APIRouter(prefix="/public/signatures", tags=["public-signatures"])
CONSENT_TEXT_DEFAULT = "Autorizo o uso da minha imagem e dados pessoais para fins de assinatura eletrônica."
CONSENT_VERSION_DEFAULT = "v1"


class PublicGroupSignPayload(SignatureAction):
    documents: List[UUID] | None = None

def _build_preview_urls(token: str) -> tuple[str, str]:
    preview_path = f"/public/signatures/{token}/preview"
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        preview_url = f"{base}{preview_path}"
    else:
        preview_url = preview_path
    download_url = f"{preview_url}?download=1"
    return preview_url, download_url


def _build_workflow_service(session: Session) -> WorkflowService:
    audit_service = AuditService(session)
    notification_service = NotificationService(
        audit_service,
        public_base_url=settings.resolved_public_app_url(),
        agent_download_url=settings.signing_agent_download_url,
        session=session,
    )
    notification_service.apply_email_settings(settings)
    if settings.twilio_account_sid and settings.twilio_auth_token:
        notification_service.configure_sms(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
            messaging_service_sid=settings.twilio_messaging_service_sid,
        )
    return WorkflowService(session, notification_service=notification_service)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _build_group_documents(session: Session, group_id: UUID | None) -> list[PublicGroupDocument] | None:
    if not group_id:
        return None
    documents = (
        session.exec(
            select(Document)
            .where(Document.group_id == group_id)
            .order_by(Document.created_at.asc())
        ).all()
    )
    if not documents:
        return []
    return [
        PublicGroupDocument(
            id=item.id,
            name=item.name,
            status=item.status.value if hasattr(item.status, "value") else str(item.status),
        )
        for item in documents
    ]


def _requires_certificate(party: DocumentParty | None) -> bool:
    """Define se a parte deve assinar com certificado digital."""
    method = (party.signature_method or "").strip().lower() if party else ""
    return method in ("digital", "certificado", "certificado digital")


def _load_public_context(
    session: Session,
    token: str,
) -> tuple[WorkflowService, SignatureRequest, WorkflowStep, DocumentParty | None, Document]:
    """Carrega o contexto completo da assinatura pÃºblica via token."""
    normalized_token = (token or "").strip()
    if not normalized_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura nÃ£o encontrada.")

    workflow_service = _build_workflow_service(session)

    try:
        data = workflow_service.get_public_signature(normalized_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura nÃ£o encontrada.")

    request: SignatureRequest = data.get("request")
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SolicitaÃ§Ã£o de assinatura invÃ¡lida.")

    if request.token_expires_at and datetime.utcnow() > request.token_expires_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link de assinatura expirado. Solicite um novo e-mail.",
        )

    step = session.get(WorkflowStep, request.workflow_step_id)
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etapa do fluxo nÃ£o encontrada.")

    document = data.get("document")
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento nÃ£o encontrado.")

    party = data.get("party")
    if not party and step.party_id:
        party = session.get(DocumentParty, step.party_id)

    if not party:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participante nÃ£o encontrado.")

    return workflow_service, request, step, party, document


def _resolve_group_context(
    session: Session,
    token: str,
) -> tuple[WorkflowService, SignatureRequest, DocumentParty, DocumentGroup, list[Document]]:
    workflow_service, request, _step, party, document = _load_public_context(session, token)
    if not document.group_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este link nÇo pertence a um lote.")
    group = session.get(DocumentGroup, document.group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo nÇo encontrado.")
    documents = (
        session.exec(
            select(Document)
            .where(Document.group_id == group.id)
            .order_by(Document.created_at.asc())
        ).all()
    )
    if not documents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum documento vinculado ao lote.")
    if not party:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participante nÇo encontrado para o lote.")
    return workflow_service, request, party, group, documents


def _only_digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _match_group_party(
    session: Session,
    document: Document,
    source_party: DocumentParty | None,
) -> DocumentParty | None:
    if not source_party:
        return None
    candidates = session.exec(
        select(DocumentParty)
        .where(DocumentParty.document_id == document.id)
        .order_by(DocumentParty.order_index.asc())
    ).all()
    if not candidates:
        return None

    source_email = (source_party.email or "").strip().lower()
    if source_email:
        for candidate in candidates:
            if (candidate.email or "").strip().lower() == source_email:
                return candidate

    source_cpf = _only_digits(source_party.cpf)
    if source_cpf:
        for candidate in candidates:
            if _only_digits(candidate.cpf) == source_cpf and source_cpf:
                return candidate

    role_key = (source_party.role or "").strip().lower()
    role_candidates = [item for item in candidates if (item.role or "").strip().lower() == role_key]
    if not role_candidates:
        return None
    source_order = source_party.order_index or 0
    for candidate in role_candidates:
        if (candidate.order_index or 0) == source_order:
            return candidate
    return role_candidates[0]


def _resolve_group_signature_request(
    session: Session,
    document: Document,
    party: DocumentParty,
) -> tuple[SignatureRequest, WorkflowInstance]:
    workflow = session.exec(
        select(WorkflowInstance)
        .where(WorkflowInstance.document_id == document.id)
        .order_by(WorkflowInstance.created_at.desc())
    ).first()
    if not workflow:
        raise ValueError("Nenhum fluxo foi iniciado para este documento.")

    step = session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == workflow.id)
        .where(WorkflowStep.party_id == party.id)
        .order_by(WorkflowStep.step_index.asc())
    ).first()
    if not step:
        raise ValueError("Participante nÃ£o faz parte do fluxo deste documento.")

    request = session.exec(
        select(SignatureRequest)
        .where(SignatureRequest.workflow_step_id == step.id)
        .order_by(SignatureRequest.created_at.desc())
    ).first()
    if not request:
        raise ValueError("Nenhum pedido de assinatura ativo para este participante.")
    return request, workflow


def _process_group_documents(
    session: Session,
    workflow_service: WorkflowService,
    documents: list[Document],
    source_party: DocumentParty,
    document_ids: list[UUID],
    action_data: dict[str, object],
    client_request: Request,
) -> list[PublicSignatureRead]:
    if not document_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selecione ao menos um documento.")
    mapped_documents = {doc.id: doc for doc in documents}
    unique_ids: list[UUID] = []
    seen: set[UUID] = set()
    for doc_id in document_ids:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        unique_ids.append(doc_id)

    ip_address = client_request.client.host if client_request.client else None
    user_agent = client_request.headers.get("user-agent")

    summaries: list[PublicSignatureRead] = []
    for doc_id in unique_ids:
        target_document = mapped_documents.get(doc_id)
        if not target_document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento selecionado nÇo encontrado.")
        target_party = _match_group_party(session, target_document, source_party)
        if not target_party:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"NÇo encontramos o participante correspondente no documento {target_document.name}.",
            )
        try:
            request_obj, workflow = _resolve_group_signature_request(session, target_document, target_party)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        action_payload = SignatureAction(**action_data)
        try:
            workflow_service._apply_signature_action(
                request_obj,
                workflow,
                target_document,
                action_payload,
                ip=ip_address,
                user_agent=user_agent,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        version = _resolve_document_version(session, target_document)
        summaries.append(_build_public_summary(session, target_document, target_party, request_obj, version))
    return summaries


def _resolve_document_version(session: Session, document: Document) -> DocumentVersion:
    """Retorna a versÃ£o mais recente do documento."""
    version = session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    if not version:
        version = session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.created_at.desc())
        ).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VersÃ£o do documento nÃ£o encontrada.")
    session.refresh(version)
    return version

def _build_public_summary(
    session: Session,
    document: Document,
    party: DocumentParty | None,
    request: SignatureRequest,
    version: DocumentVersion,
) -> PublicSignatureRead:
    mime_type = (version.mime_type or "").lower()
    supports_certificate = "pdf" in mime_type
    signature_method_raw = (party.signature_method or "electronic").strip().lower() if party else "electronic"
    normalized_method = "digital" if signature_method_raw.startswith("digital") else "electronic"
    requires_certificate = normalized_method == "digital"
    requires_cpf_confirmation = bool(requires_certificate and getattr(party, "cpf", None))
    requires_email_confirmation = bool(party and party.require_email and getattr(party, "email", None))
    requires_phone_confirmation = bool(party and party.require_phone and getattr(party, "phone_number", None))
    if hasattr(request.status, "value"):
        request_status_value = request.status.value
    else:
        request_status_value = str(request.status or "").lower()
    can_sign = request_status_value in {
        SignatureRequestStatus.PENDING.value,
        SignatureRequestStatus.SENT.value,
        "pendente",
        "enviado",
    }

    group_documents = _build_group_documents(session, document.group_id)

    return PublicSignatureRead(
        document_name=document.name,
        signer_name=party.full_name if party else "",
        status=request_status_value or "pending",
        expires_at=request.token_expires_at,
        can_sign=can_sign,
        reason=None,
        requires_email_confirmation=requires_email_confirmation,
        requires_phone_confirmation=requires_phone_confirmation,
        supports_certificate=supports_certificate,
        requires_certificate=requires_certificate,
        signature_method=normalized_method,
        requires_cpf_confirmation=requires_cpf_confirmation,
        group_id=document.group_id,
        group_documents=group_documents,
    )

def _finalize_public_signing_attempt(
    *,
    document_service: DocumentService,
    audit_service: AuditService,
    workflow_service: WorkflowService,
    document: Document,
    version: DocumentVersion,
    signature_request: SignatureRequest,
    payload: SignPdfRequest,
    attempt: SigningAgentAttempt,
    agent_response: dict[str, object],
    signed_version: DocumentVersion,
    ip_address: str | None,
    user_agent: str | None,
    token: str,
    source: str,
) -> SignPdfResponse:
    protocol = (agent_response.get("protocol") if isinstance(agent_response, dict) else None) or payload.protocol or ""
    signature_type = (
        (agent_response.get("signatureType") if isinstance(agent_response, dict) else None)
        or payload.signature_type
        or "digital"
    )
    authentication = (
        (agent_response.get("authentication") if isinstance(agent_response, dict) else None)
        or payload.authentication
        or "Certificado digital (ICP-Brasil)"
    )

    document_service.finalize_signing_agent_attempt(
        attempt,
        SigningAgentAttemptStatus.SUCCESS,
        protocol=protocol,
        agent_details={
            "signature_type": signature_type,
            "authentication": authentication,
            "source": source,
        },
    )

    audit_service.record_event(
        event_type="document_signed",
        actor_role="public",
        document_id=document.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "protocol": protocol,
            "signature_type": signature_type,
            "source": source,
        },
    )

    workflow_service.record_public_signature_action(
        token=token,
        payload=SignatureAction(
            action="sign",
            signature_type="digital",
            token=token,
            confirm_cpf=getattr(payload, "confirm_cpf", None),
        ),
        ip=ip_address,
        user_agent=user_agent,
    )

    return SignPdfResponse(
        version_id=signed_version.id,
        document_id=document.id,
        protocol=protocol,
        signature_type=signature_type,
        authentication=authentication,
    )


class PublicMeta(BaseModel):
    """InformaÃ§Ãµes pÃºblicas de um token de assinatura."""
    document_id: str
    participant_id: str
    requires_certificate: bool
    status: str
    document_name: str | None = None
    signer_name: str | None = None
    version_id: str | None = None
    requires_email_confirmation: bool = False
    requires_phone_confirmation: bool = False
    supports_certificate: bool = False
    signature_method: str = "electronic"
    typed_name_required: bool = False
    collect_typed_name: bool = False
    collect_signature_image: bool = False
    signature_image_required: bool = False
    requires_consent: bool = False
    consent_text: str | None = None
    consent_version: str | None = None
    available_fields: list[str] | None = None
    requires_cpf_confirmation: bool = False
    can_sign: bool = False
    allow_typed_name: bool = False
    allow_signature_image: bool = False
    allow_signature_draw: bool = False


@router.get("/{token}/meta", response_model=PublicMeta)
def get_public_meta(token: str, session: Session = Depends(get_db)) -> PublicMeta:
    _, request, step, party, document = _load_public_context(session, token)

    version: DocumentVersion | None = None
    if document.current_version_id:
        version = session.get(DocumentVersion, document.current_version_id)
    if not version:
        version = session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.created_at.desc())
        ).first()

    supports_certificate = bool(
        version and "pdf" in ((version.mime_type or "").lower() if version.mime_type else "")
    )
    require_email_confirmation = bool(party and party.require_email and getattr(party, "email", None))
    require_phone_confirmation = bool(party and party.require_phone and getattr(party, "phone_number", None))

    role_key = (party.role or "").strip().lower() if party and party.role else ""
    field_query = select(DocumentField).where(DocumentField.document_id == document.id)
    if version:
        field_query = field_query.where(DocumentField.version_id == version.id)

    filtered_fields = session.exec(field_query).all()
    if role_key:
        filtered_fields = [
            field for field in filtered_fields if (field.role or "").strip().lower() == role_key
        ]

    typed_required = any(field.field_type == "typed_name" and field.required for field in filtered_fields)
    image_required = any(field.field_type == "signature_image" and field.required for field in filtered_fields)
    allow_typed_name = bool(party and party.allow_typed_name)
    allow_signature_image = bool(party and party.allow_signature_image)
    allow_signature_draw = bool(party and party.allow_signature_draw)
    collect_typed_name = allow_typed_name or typed_required
    collect_signature_image = allow_signature_image or image_required
    consent_text = CONSENT_TEXT_DEFAULT if collect_signature_image else None
    consent_version = CONSENT_VERSION_DEFAULT if collect_signature_image else None

    signature_method_raw = (party.signature_method or "electronic").strip().lower() if party else "electronic"
    normalized_signature_method = "digital" if signature_method_raw.startswith("digital") else signature_method_raw
    requires_certificate = _requires_certificate(party)
    requires_cpf_confirmation = bool(requires_certificate and getattr(party, "cpf", None))
    preview_url, download_url = _build_preview_urls(token)
    signer_tax_id = getattr(party, "cpf", None)
    can_sign = request.status in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT}

    group_documents = _build_group_documents(session, document.group_id)

    return PublicMeta(
        document_id=str(document.id),
        participant_id=str(step.party_id or (party.id if party else "")),
        requires_certificate=requires_certificate,
        status=request.status.value if hasattr(request.status, "value") else str(request.status),
        document_name=document.name,
        signer_name=party.full_name if party else None,
        version_id=str(version.id) if version else None,
        requires_email_confirmation=require_email_confirmation,
        requires_phone_confirmation=require_phone_confirmation,
        supports_certificate=supports_certificate,
        signature_method=normalized_signature_method,
        typed_name_required=typed_required and collect_typed_name,
        collect_typed_name=collect_typed_name,
        collect_signature_image=collect_signature_image,
        signature_image_required=image_required and collect_signature_image,
        requires_consent=collect_signature_image,
        consent_text=consent_text,
        consent_version=consent_version,
        available_fields=[field.field_type for field in filtered_fields],
        can_sign=can_sign,
        reason=None,
        preview_url=preview_url,
        download_url=download_url,
        signer_tax_id=signer_tax_id,
        requires_cpf_confirmation=requires_cpf_confirmation,
        group_id=document.group_id,
        group_documents=group_documents,
        allow_typed_name=allow_typed_name,
        allow_signature_image=allow_signature_image,
        allow_signature_draw=allow_signature_draw,
    )

@router.get("/{token}/fields", response_model=List[DocumentFieldRead])
def get_public_fields(token: str, session: Session = Depends(get_db)) -> List[DocumentFieldRead]:
    _, _, _, party, document = _load_public_context(session, token)
    version = _resolve_document_version(session, document)
    document_service = DocumentService(session)
    fields = document_service.list_fields(document, version)
    role_key = (party.role or "").strip().lower() if party and party.role else ""
    filtered = [
        field
        for field in fields
        if not role_key or (field.role or "").strip().lower() == role_key
    ]
    return [DocumentFieldRead.model_validate(field, from_attributes=True) for field in filtered]


@router.post("/{token}/group-sign", response_model=List[PublicSignatureRead])
def group_public_sign(
    token: str,
    payload: PublicGroupSignPayload,
    request: Request,
    session: Session = Depends(get_db),
) -> List[PublicSignatureRead]:
    if not payload.documents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selecione ao menos um documento.")
    workflow_service, _request_obj, party, _group, documents = _resolve_group_context(session, token)
    action_data = payload.model_dump(exclude={"documents"})
    action_data["token"] = token
    return _process_group_documents(
        session=session,
        workflow_service=workflow_service,
        documents=documents,
        source_party=party,
        document_ids=payload.documents,
        action_data=action_data,
        client_request=request,
    )


@router.post("/{token}", response_model=PublicSignatureRead)
def act_public_sign(
    token: str,
    payload: PublicGroupSignPayload,
    request: Request,
    session: Session = Depends(get_db),
) -> PublicSignatureRead:
    """Assinatura publica via link do e-mail."""
    if payload.action != "sign":
        raise HTTPException(status_code=400, detail="Acao nao suportada.")

    workflow_service, request_obj, _step, party, document = _load_public_context(session, token)

    if payload.signed_pdf and party:
        current_method = (party.signature_method or "electronic").strip().lower() if party else "electronic"
        if current_method not in {"digital", "certificado", "certificado digital", "icp", "icp-brasil"}:
            party.signature_method = "digital"
            session.add(party)
            session.commit()
            session.refresh(party)

    try:
        payload_data = payload.model_dump(exclude_unset=True)
        payload_data["token"] = token
        workflow_service.record_public_signature_action(
            token=token,
            payload=SignatureAction(**payload_data),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    extra_documents = [doc_id for doc_id in (payload.documents or []) if document.group_id and doc_id != document.id]
    if extra_documents and document.group_id and party:
        group_documents = (
            session.exec(
                select(Document)
                .where(Document.group_id == document.group_id)
                .order_by(Document.created_at.asc())
            ).all()
        )
        action_data = payload.model_dump(exclude={"documents"})
        action_data["token"] = token
        _process_group_documents(
            session=session,
            workflow_service=workflow_service,
            documents=group_documents,
            source_party=party,
            document_ids=extra_documents,
            action_data=action_data,
            client_request=request,
        )

    _, request_obj, _step, party, document = _load_public_context(session, token)
    version = _resolve_document_version(session, document)
    summary = _build_public_summary(session, document, party, request_obj, version)
    return summary


@router.post("/{token}/agent/session", response_model=PublicAgentSessionStartResponse)
def start_public_agent_session(
    token: str,
    payload: PublicAgentSessionStartPayload,
    session: Session = Depends(get_db),
) -> PublicAgentSessionStartResponse:
    """Prepara uma sessÃ£o de assinatura para execuÃ§Ã£o no agente local do assinante."""
    workflow_service, signature_request, _, party, document = _load_public_context(session, token)
    if not _requires_certificate(party):
        raise HTTPException(status_code=400, detail="Esta assinatura nÃ£o exige certificado digital.")

    version = _resolve_document_version(session, document)
    document_service = DocumentService(session)

    request_payload = SignPdfRequest(**payload.model_dump(exclude_none=True))
    if request_payload.cert_index is None and not request_payload.thumbprint:
        raise HTTPException(status_code=400, detail="Selecione um certificado para continuar.")
    request_payload.signature_type = request_payload.signature_type or "digital"
    request_payload.authentication = request_payload.authentication or "Certificado digital (ICP-Brasil)"

    attempt = document_service.create_signing_agent_attempt(
        document=document,
        version=version,
        actor_id=None,
        actor_role="public",
        payload=request_payload,
    )
    agent_payload = document_service.build_signing_agent_payload(
        document=document,
        version=version,
        request=request_payload,
    )
    return PublicAgentSessionStartResponse(attempt_id=attempt.id, payload=agent_payload)


@router.post("/{token}/agent/session/{attempt_id}/complete", response_model=SignPdfResponse)
def complete_public_agent_session(
    token: str,
    attempt_id: UUID,
    payload: PublicAgentSessionCompletePayload,
    request: Request,
    session: Session = Depends(get_db),
) -> SignPdfResponse:
    """Finaliza a sessÃ£o de assinatura enviando o PDF assinado pelo agente local."""
    from app.core.logging_setup import logger
    logger.info(f"[PUBLIC_COMPLETE] Iniciando complete para token={token}, attempt_id={attempt_id}")
    
    try:
        workflow_service, signature_request, _, party, document = _load_public_context(session, token)
        logger.info(f"[PUBLIC_COMPLETE] Context carregado: document_id={document.id}, party_id={party.id if party else None}")
        
        if not _requires_certificate(party):
            logger.warning(f"[PUBLIC_COMPLETE] Assinatura nÃ£o requer certificado digital")
            raise HTTPException(status_code=400, detail="Esta assinatura nÃ£o exige certificado digital.")

        version = _resolve_document_version(session, document)
        logger.info(f"[PUBLIC_COMPLETE] Version resolvida: version_id={version.id}")
        
        document_service = DocumentService(session)
        audit_service = AuditService(session)

        attempt = session.get(SigningAgentAttempt, attempt_id)
        if not attempt or attempt.document_id != document.id or attempt.version_id != version.id:
            logger.error(f"[PUBLIC_COMPLETE] Tentativa nÃ£o encontrada ou invÃ¡lida")
            raise HTTPException(status_code=404, detail="Tentativa de assinatura nÃ£o encontrada.")
        if attempt.status != SigningAgentAttemptStatus.PENDING:
            logger.error(f"[PUBLIC_COMPLETE] Tentativa jÃ¡ processada: status={attempt.status}")
            raise HTTPException(status_code=400, detail="Esta tentativa jÃ¡ foi processada.")

        request_payload = SignPdfRequest(**(attempt.payload or {}))
        # Para assinaturas pÃºblicas, nÃ£o hÃ¡ user_id (o signatÃ¡rio nÃ£o Ã© um usuÃ¡rio do sistema)
        
        logger.info(f"[PUBLIC_COMPLETE] Processando PDF assinado...")
        signed_version = document_service.save_signed_pdf_from_agent_response(
            document=document,
            version=version,
            agent_response=payload.agent_response,
            user_id=None,  # Assinatura pÃºblica nÃ£o tem user_id
        )
        logger.info(f"[PUBLIC_COMPLETE] PDF processado com sucesso: signed_version_id={signed_version.id}")
        
    except SigningAgentError as exc:
        logger.error(f"[PUBLIC_COMPLETE] SigningAgentError: {exc}")
        document_service.finalize_signing_agent_attempt(
            attempt,
            SigningAgentAttemptStatus.ERROR,
            error_message=str(exc),
        )
        raise HTTPException(status_code=400, detail=f"Falha ao validar PDF assinado: {exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - proteÃ§Ã£o adicional
        logger.exception(f"[PUBLIC_COMPLETE] Erro inesperado: {exc}")
        document_service.finalize_signing_agent_attempt(
            attempt,
            SigningAgentAttemptStatus.ERROR,
            error_message=str(exc),
        )
        raise HTTPException(status_code=400, detail="NÃ£o foi possÃ­vel processar o PDF assinado.") from exc

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    logger.info(f"[PUBLIC_COMPLETE] Finalizando assinatura...")
    return _finalize_public_signing_attempt(
        document_service=document_service,
        audit_service=audit_service,
        workflow_service=workflow_service,
        document=document,
        version=version,
        signature_request=signature_request,
        payload=request_payload,
        attempt=attempt,
        agent_response=payload.agent_response,
        signed_version=signed_version,
        ip_address=ip_address,
        user_agent=user_agent,
        token=token,
        source="browser-agent",
    )
@router.get("/{token}", response_model=PublicSignatureRead)
def get_public_signature(
    token: str,
    session: Session = Depends(get_db),
) -> PublicSignatureRead:
    workflow_service, request_obj, _step, party, document = _load_public_context(session, token)
    if request_obj.status not in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura indisponivel.")
    version = _resolve_document_version(session, document)
    return _build_public_summary(session, document, party, request_obj, version)








