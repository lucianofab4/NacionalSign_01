from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.document import Document, DocumentParty, DocumentVersion
from app.models.signing import SigningAgentAttemptStatus
from app.models.workflow import SignatureRequest, WorkflowStep
from app.schemas.signing_agent import SigningCertificate, SignPdfRequest, SignPdfResponse
from app.schemas.workflow import SignatureAction
from app.services.audit import AuditService
from app.services.document import DocumentService
from app.services.signing_agent import SigningAgentClient, SigningAgentError
from app.services.workflow import WorkflowService

router = APIRouter(prefix="/public/signatures", tags=["public-signatures"])


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
    workflow_service = WorkflowService(session)

    try:
        data = workflow_service.get_public_signature(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assinatura não encontrada.")

    request: SignatureRequest = data.get("request")
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitação de assinatura inválida.")

    if request.token_expires_at and datetime.utcnow() > request.token_expires_at:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token de assinatura expirado.")

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


def _fetch_signing_agent_certificates() -> list[SigningCertificate]:
    """Busca certificados disponíveis no agente local."""
    try:
        client = SigningAgentClient()
        raw_items = list(client.list_certificates())
    except SigningAgentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    certificates: list[SigningCertificate] = []
    for idx, item in enumerate(raw_items):
        subject = item.get("subject") or item.get("Subject")
        if not subject:
            continue
        certificates.append(
            SigningCertificate(
                index=item.get("index", idx),
                subject=subject,
                issuer=item.get("issuer") or item.get("Issuer", ""),
                serial_number=item.get("serialNumber") or item.get("serial") or item.get("SerialNumber"),
                thumbprint=item.get("thumbprint") or item.get("Thumbprint"),
                not_before=item.get("notBefore") or item.get("NotBefore"),
                not_after=item.get("notAfter") or item.get("NotAfter"),
            )
        )

    if not certificates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum certificado digital encontrado.")

    return certificates


def _execute_public_signing_agent(
    *,
    document_service: DocumentService,
    audit_service: AuditService,
    workflow_service: WorkflowService,
    document: Document,
    version: DocumentVersion,
    payload: SignPdfRequest,
    signature_request: SignatureRequest,
    request: Request,
    token: str,
) -> SignPdfResponse:
    """Executa a assinatura digital via agente local."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    attempt = document_service.create_signing_agent_attempt(
        document=document,
        version=version,
        actor_id=None,
        actor_role="public",
        payload=payload,
    )

    try:
        signed_version, agent_response = document_service.sign_version_with_agent(
            document,
            version,
            payload,
            actor_reference=str(signature_request.party_id or signature_request.id),
        )
    except SigningAgentError as exc:
        document_service.finalize_signing_agent_attempt(
            attempt,
            SigningAgentAttemptStatus.ERROR,
            error_message=str(exc),
        )
        raise HTTPException(status_code=502, detail=f"Falha na comunicação com agente local: {exc}") from exc

    protocol = agent_response.get("protocol") or payload.protocol or ""
    signature_type = agent_response.get("signatureType") or "digital"

    document_service.finalize_signing_agent_attempt(
        attempt,
        SigningAgentAttemptStatus.SUCCESS,
        protocol=protocol,
        agent_details={"signature_type": signature_type},
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
            "source": "signing-agent-public",
        },
    )

    # Atualiza o fluxo
    workflow_service.record_public_signature_action(
        token=token,
        payload=SignatureAction(action="sign", signature_type="digital", token=token),
        ip=ip_address,
        user_agent=user_agent,
    )

    return SignPdfResponse(
        version_id=signed_version.id,
        document_id=document.id,
        protocol=protocol,
        signature_type=signature_type,
        authentication="Certificado digital (ICP-Brasil)",
    )


class PublicMeta(BaseModel):
    """Informações públicas de um token de assinatura."""
    document_id: str
    participant_id: str
    requires_certificate: bool
    status: str


class PublicSignIn(BaseModel):
    """Entrada para ação pública (assinar)."""
    action: Literal["sign"]
    signature_type: Literal["digital", "electronic"]


@router.get("/{token}/meta", response_model=PublicMeta)
def get_public_meta(token: str, session: Session = Depends(get_db)) -> PublicMeta:
    _, request, step, party, document = _load_public_context(session, token)

    return PublicMeta(
        document_id=str(document.id),
        participant_id=str(step.party_id or (party.id if party else "")),
        requires_certificate=_requires_certificate(party),
        status=request.status.value if hasattr(request.status, "value") else str(request.status),
    )


@router.post("/{token}")
def act_public_sign(token: str, payload: PublicSignIn, session: Session = Depends(get_db)) -> dict[str, object]:
    """Assinatura pública via link do e-mail."""
    if payload.action != "sign":
        raise HTTPException(status_code=400, detail="Ação não suportada.")

    workflow_service = WorkflowService(session)
    try:
        signature_request = workflow_service.record_public_signature_action(
            token=token,
            payload=SignatureAction(
                action=payload.action,
                signature_type=payload.signature_type,
                token=token,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "status": signature_request.status.value if hasattr(signature_request.status, "value") else str(signature_request.status),
    }


@router.get("/{token}/agent/certificates", response_model=List[SigningCertificate])
def list_public_agent_certificates(token: str, session: Session = Depends(get_db)) -> List[SigningCertificate]:
    """Lista certificados disponíveis para assinatura digital."""
    _, _, _, party, _ = _load_public_context(session, token)
    if not _requires_certificate(party):
        raise HTTPException(status_code=400, detail="Esta assinatura não exige certificado digital.")
    return _fetch_signing_agent_certificates()


@router.post("/{token}/agent/sign", response_model=SignPdfResponse)
def sign_public_with_agent(
    token: str,
    payload: SignPdfRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> SignPdfResponse:
    """Executa a assinatura pública com certificado (ICP)."""
    workflow_service, signature_request, _, party, document = _load_public_context(session, token)

    if not _requires_certificate(party):
        raise HTTPException(status_code=400, detail="Esta assinatura não exige certificado digital.")

    version = _resolve_document_version(session, document)
    document_service = DocumentService(session)
    audit_service = AuditService(session)

    return _execute_public_signing_agent(
        document_service=document_service,
        audit_service=audit_service,
        workflow_service=workflow_service,
        document=document,
        version=version,
        payload=payload,
        signature_request=signature_request,
        request=request,
        token=token,
    )
