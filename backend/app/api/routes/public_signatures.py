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
from app.models.document import Document, DocumentParty, DocumentVersion, DocumentField
from app.models.signing import SigningAgentAttempt, SigningAgentAttemptStatus
from app.models.workflow import SignatureRequest, SignatureRequestStatus, WorkflowStep
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
from app.schemas.public import PublicSignatureRead
from app.services.audit import AuditService
from app.services.document import DocumentService
from app.services.notification import NotificationService
from app.services.signing_agent import SigningAgentError
from app.services.workflow import WorkflowService

router = APIRouter(prefix="/public/signatures", tags=["public-signatures"])
CONSENT_TEXT_DEFAULT = "Autorizo o uso da minha imagem e dados pessoais para fins de assinatura eletrônica."
CONSENT_VERSION_DEFAULT = "v1"

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


def _requires_certificate(party: DocumentParty | None) -> bool:
    """Define se a parte deve assinar com certificado digital."""
    method = (party.signature_method or "").strip().lower() if party else ""
    return method in ("digital", "certificado", "certificado digital")


def _load_public_context(
    session: Session,
    token: str,
) -> tuple[WorkflowService, SignatureRequest, WorkflowStep, DocumentParty | None, Document]:
    """Carrega o contexto completo da assinatura pública via token."""
    normalized_token = (token or "").strip()
    if not normalized_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura não encontrada.")

    workflow_service = _build_workflow_service(session)

    try:
        data = workflow_service.get_public_signature(normalized_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura não encontrada.")

    request: SignatureRequest = data.get("request")
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação de assinatura inválida.")

    if request.token_expires_at and datetime.utcnow() > request.token_expires_at:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link de assinatura expirado. Solicite um novo e-mail.",
        )

    step = session.get(WorkflowStep, request.workflow_step_id)
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etapa do fluxo não encontrada.")

    document = data.get("document")
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento não encontrado.")

    party = data.get("party")
    if not party and step.party_id:
        party = session.get(DocumentParty, step.party_id)

    if not party:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participante não encontrado.")

    return workflow_service, request, step, party, document


def _resolve_document_version(session: Session, document: Document) -> DocumentVersion:
    """Retorna a versão mais recente do documento."""
    version = session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    if not version:
        version = session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.created_at.desc())
        ).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versão do documento não encontrada.")
    session.refresh(version)
    return version

def _build_public_summary(
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
        "pending",
        "sent",
    }

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
    """Informações públicas de um token de assinatura."""
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


@router.post("/{token}", response_model=PublicSignatureRead)
def act_public_sign(
    token: str,
    payload: SignatureAction,
    session: Session = Depends(get_db),
) -> PublicSignatureRead:
    """Assinatura publica via link do e-mail."""
    if payload.action != "sign":
        raise HTTPException(status_code=400, detail="Acao nao suportada.")

    workflow_service, request_obj, _step, party, document = _load_public_context(session, token)

    if payload.signed_pdf and party:
        current_method = (party.signature_method or "").strip().lower()
        if current_method not in {"digital", "certificado", "certificado digital", "icp", "icp-brasil"}:
            party.signature_method = "digital"
            session.add(party)
            session.commit()
            session.refresh(party)

    try:
        workflow_service.record_public_signature_action(
            token=token,
            payload=SignatureAction(**payload.model_dump(exclude_unset=True), token=token),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _, request_obj, _step, party, document = _load_public_context(session, token)
    version = _resolve_document_version(session, document)
    summary = _build_public_summary(document, party, request_obj, version)
    return summary


@router.post("/{token}/agent/session", response_model=PublicAgentSessionStartResponse)
def start_public_agent_session(
    token: str,
    payload: PublicAgentSessionStartPayload,
    session: Session = Depends(get_db),
) -> PublicAgentSessionStartResponse:
    """Prepara uma sessão de assinatura para execução no agente local do assinante."""
    workflow_service, signature_request, _, party, document = _load_public_context(session, token)
    if not _requires_certificate(party):
        raise HTTPException(status_code=400, detail="Esta assinatura não exige certificado digital.")

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
    """Finaliza a sessão de assinatura enviando o PDF assinado pelo agente local."""
    from app.core.logging_setup import logger
    logger.info(f"[PUBLIC_COMPLETE] Iniciando complete para token={token}, attempt_id={attempt_id}")
    
    try:
        workflow_service, signature_request, _, party, document = _load_public_context(session, token)
        logger.info(f"[PUBLIC_COMPLETE] Context carregado: document_id={document.id}, party_id={party.id if party else None}")
        
        if not _requires_certificate(party):
            logger.warning(f"[PUBLIC_COMPLETE] Assinatura não requer certificado digital")
            raise HTTPException(status_code=400, detail="Esta assinatura não exige certificado digital.")

        version = _resolve_document_version(session, document)
        logger.info(f"[PUBLIC_COMPLETE] Version resolvida: version_id={version.id}")
        
        document_service = DocumentService(session)
        audit_service = AuditService(session)

        attempt = session.get(SigningAgentAttempt, attempt_id)
        if not attempt or attempt.document_id != document.id or attempt.version_id != version.id:
            logger.error(f"[PUBLIC_COMPLETE] Tentativa não encontrada ou inválida")
            raise HTTPException(status_code=404, detail="Tentativa de assinatura não encontrada.")
        if attempt.status != SigningAgentAttemptStatus.PENDING:
            logger.error(f"[PUBLIC_COMPLETE] Tentativa já processada: status={attempt.status}")
            raise HTTPException(status_code=400, detail="Esta tentativa já foi processada.")

        request_payload = SignPdfRequest(**(attempt.payload or {}))
        # Para assinaturas públicas, não há user_id (o signatário não é um usuário do sistema)
        
        logger.info(f"[PUBLIC_COMPLETE] Processando PDF assinado...")
        signed_version = document_service.save_signed_pdf_from_agent_response(
            document=document,
            version=version,
            agent_response=payload.agent_response,
            user_id=None,  # Assinatura pública não tem user_id
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
    except Exception as exc:  # pragma: no cover - proteção adicional
        logger.exception(f"[PUBLIC_COMPLETE] Erro inesperado: {exc}")
        document_service.finalize_signing_agent_attempt(
            attempt,
            SigningAgentAttemptStatus.ERROR,
            error_message=str(exc),
        )
        raise HTTPException(status_code=400, detail="Não foi possível processar o PDF assinado.") from exc

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
    version = _resolve_document_version(session, document)
    mime_type = (version.mime_type or "").lower()
    supports_certificate = "pdf" in mime_type
    signature_method = (party.signature_method or "electronic").strip().lower() if party else "electronic"
    normalized_method = "digital" if signature_method.startswith("digital") else "electronic"
    if request_obj.status not in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura indisponível.")

    requires_certificate = normalized_method == "digital"
    requires_email_confirmation = bool(party and party.require_email and getattr(party, "email", None))
    requires_phone_confirmation = bool(party and party.require_phone and getattr(party, "phone_number", None))

    return PublicSignatureRead(
        document_name=document.name,
        signer_name=party.full_name if party else "",
        status=request_obj.status.value,
        expires_at=request_obj.token_expires_at,
        can_sign=request_obj.status in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT},
        reason=None,
        requires_email_confirmation=requires_email_confirmation,
        requires_phone_confirmation=requires_phone_confirmation,
        supports_certificate=supports_certificate,
        requires_certificate=requires_certificate,
        signature_method=normalized_method,
    )







