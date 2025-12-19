import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.api.deps import get_current_active_user, get_db, require_roles
from app.db.session import get_session
from app.models.audit import AuditLog
from app.models.document import (
    AuditArtifact,
    Document,
    DocumentField,
    DocumentParty,
    DocumentStatus,
    DocumentVersion,
)
from app.models.user import User, UserRole
from app.schemas.document import (
    DocumentArchiveRequest,
    DocumentCreate,
    DocumentPartyCreate,
    DocumentPartyRead,
    DocumentPartyUpdate,
    DocumentRead,
    DocumentUpdate,
    DocumentVersionRead,
    DocumentFieldCreate,
    DocumentFieldRead,
    DocumentFieldUpdate,
    DocumentSignatureInfo,
)
from app.models.signing import SigningAgentAttemptStatus
from app.models.workflow import Signature, SignatureRequest, WorkflowInstance, WorkflowStep
from app.schemas.signing_agent import SigningCertificate, SignAgentAttemptRead, SignPdfRequest, SignPdfResponse
from app.services.audit import AuditService
from app.services.document import DocumentService
from app.services.storage import get_storage, resolve_storage_root
from app.services.signing_agent import SigningAgentClient, SigningAgentError

SIGNATURE_MARKERS = (
    b"NacionalSign Fallback",
    b"/NSDigest",
    b"/ETSI.RFC3161",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_storage_file_path(storage_path: str | None) -> Path | None:
    """
    Resolve caminhos relativos para o local correto no disco.

    Em instala��es anteriores os PDFs ficaram em "storage/" enquanto a
    configura��o atual aponta para "_storage/". O helper abaixo tenta todas as
    possibilidades antes de desistir.
    """
    if not storage_path:
        return None

    raw_path = Path(storage_path)
    candidates: list[Path] = []

    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        base_root = resolve_storage_root()
        candidates.append(base_root / storage_path)

        legacy_root = base_root.parent / "storage"
        if legacy_root != base_root:
            candidates.append(legacy_root / storage_path)

        candidates.append(_PROJECT_ROOT / storage_path)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved.exists():
            return resolved

    return None


def _looks_like_signed_pdf(storage_path: str) -> bool:
    storage = get_storage()
    try:
        data = storage.load_bytes(storage_path)
    except Exception:
        return False
    if not data:
        return False
    sample = data if len(data) <= 8192 else data[:8192]
    return any(marker in sample for marker in SIGNATURE_MARKERS)


def _collect_pkcs7_paths(version: DocumentVersion) -> list[str]:
    """
    Encontra arquivos .p7s no mesmo diretório do PDF assinado final.
    Esse método é utilizado por outras partes do sistema (ex: _build_version_read)
    por isso precisa estar alinhado com _load_pkcs7_files.
    """
    storage_path = version.storage_path or ""
    if not storage_path:
        return []

    file_path = _resolve_storage_file_path(storage_path)
    if not file_path:
        return []

    parent = file_path.parent
    stem = file_path.name  # deve ser o NOME EXATO do arquivo final

    return [
        str(path)
        for path in sorted(parent.glob(f"{stem}*.p7s"))
        if path.is_file()
    ]


def _party_requires_certificate(party: DocumentParty | None) -> bool:
    method = (party.signature_method or "").lower() if party and party.signature_method else ""
    return method == "digital"


def _party_to_read(party: DocumentParty) -> DocumentPartyRead:
    base = DocumentPartyRead.model_validate(party, from_attributes=True)
    return base.copy(update={"requires_certificate": _party_requires_certificate(party)})


def _get_latest_version(session: Session, document: Document) -> DocumentVersion:
    version_id = getattr(document, "current_version_id", None)
    version = session.get(DocumentVersion, version_id) if version_id else None
    if not version:
        version = session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.created_at.desc())
        ).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return version



def _load_signed_pdf(version: DocumentVersion) -> bytes:
    '''Carrega os bytes do PDF assinado a partir do storage_path.'''
    if not version.storage_path:
        raise FileNotFoundError('Versão não possui storage_path definido.')

    storage_path = version.storage_path
    file_path = _resolve_storage_file_path(storage_path)
    if not file_path or not file_path.exists():
        raise FileNotFoundError(
            'Arquivo de PDF assinado não foi encontrado no armazenamento configurado.'
        )

    return file_path.read_bytes()


def _load_pkcs7_files(version: DocumentVersion) -> list[tuple[str, bytes]]:
    '''Procura arquivos .p7s na mesma pasta do PDF assinado.'''
    if not version.storage_path:
        return []

    file_path = _resolve_storage_file_path(version.storage_path)
    if not file_path:
        return []

    parent = file_path.parent
    if not parent.exists():
        return []

    results: list[tuple[str, bytes]] = []
    pattern = f"{file_path.name}*.p7s"
    for p7s_file in parent.glob(pattern):
        try:
            content = p7s_file.read_bytes()
            results.append((p7s_file.name, content))
        except OSError:
            continue

    return results


def _resolve_signed_filename(version: DocumentVersion) -> str:
    candidate = version.original_filename or ""
    if not candidate:
        storage_path = version.storage_path or ""
        if storage_path:
            candidate = Path(storage_path).name
        else:
            candidate = f"{version.id}.pdf"
    candidate = candidate.replace("\\", "/").split("/")[-1]
    if not candidate.lower().endswith(".pdf"):
        candidate += ".pdf"
    return candidate


router = APIRouter(prefix="/documents", tags=["documents"])


def _services(session: Session) -> tuple[DocumentService, AuditService]:
    return DocumentService(session), AuditService(session)


def _execute_signing_agent(
    *,
    document_service: DocumentService,
    audit_service: AuditService,
    document: Document,
    version: DocumentVersion,
    payload: SignPdfRequest,
    current_user: User,
    request: Request,
) -> SignPdfResponse:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    attempt = document_service.create_signing_agent_attempt(
        document,
        version,
        actor_id=current_user.id,
        actor_role=current_user.profile,
        payload=payload,
    )

    try:
        signed_version, agent_response = document_service.sign_version_with_agent(
            document,
            version,
            payload,
            current_user.id,
        )
    except SigningAgentError as exc:
        document_service.finalize_signing_agent_attempt(
            attempt,
            SigningAgentAttemptStatus.ERROR,
            error_message=str(exc),
            agent_details=getattr(exc, "details", None),
        )
        audit_service.record_event(
            event_type="document_sign_agent_failed",
            actor_id=current_user.id,
            actor_role=current_user.profile,
            document_id=document.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                "version_id": str(version.id),
                "error": str(exc),
                "agent_details": getattr(exc, "details", None),
                "attempt_id": str(attempt.id),
            },
        )
        status_code = exc.status_code or status.HTTP_502_BAD_GATEWAY
        detail_payload: dict[str, object] = {
            "error": str(exc),
            "attempt_id": str(attempt.id),
        }
        if getattr(exc, "details", None) is not None:
            detail_payload["agent_details"] = exc.details
        raise HTTPException(status_code=status_code, detail=detail_payload) from exc
    except ValueError as exc:
        document_service.finalize_signing_agent_attempt(
            attempt,
            SigningAgentAttemptStatus.ERROR,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc), "attempt_id": str(attempt.id)},
        ) from exc

    protocol_value = (
        agent_response.get("protocol")
        or agent_response.get("Protocol")
        or payload.protocol
        or ""
    )
    signature_type = agent_response.get("signatureType") or agent_response.get("SignatureType")
    authentication = agent_response.get("authentication") or agent_response.get("Authentication")

    document_service.finalize_signing_agent_attempt(
        attempt,
        SigningAgentAttemptStatus.SUCCESS,
        protocol=protocol_value,
        agent_details={
            key: value
            for key, value in {
                "signature_type": signature_type,
                "authentication": authentication,
            }.items()
            if value is not None
        },
    )

    audit_service.record_event(
        event_type="document_signed",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "version_id": str(signed_version.id),
            "protocol": protocol_value,
            "signature_type": signature_type,
            "authentication": authentication,
            "source": "signing-agent",
            "attempt_id": str(attempt.id),
        },
    )

    return SignPdfResponse(
        version_id=signed_version.id,
        document_id=document.id,
        protocol=protocol_value,
        signature_type=signature_type,
        authentication=authentication,
    )


def _build_version_read(
    session: Session,
    document_service: DocumentService,
    document: Document,
    version: DocumentVersion,
) -> DocumentVersionRead:
    storage_path_value = version.storage_path or ""
    file_name = Path(storage_path_value).name if storage_path_value else ""
    icp_signed = file_name.startswith("final-")
    if not icp_signed:
        icp_signed = _looks_like_signed_pdf(storage_path_value)
    icp_timestamp: datetime | None = None
    icp_authority: str | None = None

    # 🔍 Busca dados de assinatura ICP (caso exista)
    if icp_signed:
        audit_rows = session.exec(
            select(AuditLog)
            .where(AuditLog.document_id == document.id)
            .where(AuditLog.event_type == "document_signed")
            .order_by(AuditLog.created_at.desc())
        ).all()
        for audit_row in audit_rows:
            details = audit_row.details or {}
            if details.get("version_id") == str(version.id):
                authority_value = details.get("authority")
                if isinstance(authority_value, str):
                    icp_authority = authority_value
                issued_at_raw = details.get("issued_at")
                if isinstance(issued_at_raw, str):
                    try:
                        icp_timestamp = datetime.fromisoformat(issued_at_raw)
                    except ValueError:
                        icp_timestamp = audit_row.created_at
                if icp_timestamp is None:
                    icp_timestamp = audit_row.created_at
                break

        if icp_timestamp is None:
            timestamp_artifact = session.exec(
                select(AuditArtifact)
                .where(AuditArtifact.document_id == document.id)
                .where(AuditArtifact.artifact_type == "signed_pdf_timestamp")
                .order_by(AuditArtifact.created_at.desc())
            ).first()
            if timestamp_artifact and timestamp_artifact.issued_at:
                icp_timestamp = timestamp_artifact.issued_at

        if icp_timestamp is None:
            icp_timestamp = version.updated_at or version.created_at

    # ✅ Novo: identificar nome do usuário que enviou (pode ser None)
    uploader = session.get(User, version.uploaded_by_id) if getattr(version, "uploaded_by_id", None) else None

    # 🔍 Campos e marcações de assinatura
    fields = document_service.list_fields(document, version)
    field_payload = [
        DocumentFieldRead.model_validate(field, from_attributes=True)
        for field in fields
    ]

    # 🔍 Verifica pacotes .p7s e relatórios
    pkcs7_paths = _collect_pkcs7_paths(version)
    has_pkcs7 = bool(pkcs7_paths)
    icp_report_url = (
        f"/api/v1/documents/{document.id}/versions/{version.id}/report"
        if icp_signed or has_pkcs7
        else None
    )
    icp_public_report_url = f"/public/verification/{document.id}/report" if icp_signed else None
    preview_url = f"/api/v1/documents/{document.id}/versions/{version.id}/content"

    # ✅ Retorno completo atualizado
    return DocumentVersionRead(
        id=version.id,
        created_at=version.created_at,
        updated_at=version.updated_at,
        document_id=version.document_id,
        storage_path=storage_path_value,
        original_filename=version.original_filename,
        mime_type=version.mime_type,
        size_bytes=version.size_bytes,
        sha256=version.sha256,
        uploaded_by_id=getattr(version, "uploaded_by_id", None),
        uploaded_by_full_name=getattr(uploader, "full_name", None),  # novo campo incluído
        icp_signed=icp_signed,
        icp_timestamp=icp_timestamp,
        icp_authority=icp_authority,
        icp_report_url=icp_report_url,
        icp_public_report_url=icp_public_report_url,
        icp_signature_bundle_available=has_pkcs7 or None,
        fields=field_payload,
        preview_url=preview_url,
    )

@router.get("", response_model=List[DocumentRead])
def list_documents(
    area_id: UUID | None = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[DocumentRead]:
    document_service, _ = _services(session)
    return list(document_service.list_documents(current_user.tenant_id, area_id))


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER, UserRole.USER)),
) -> DocumentRead:
    document_service, audit_service = _services(session)
    try:
        document = document_service.create_document(current_user.tenant_id, current_user.id, payload)
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_service.record_event(
        event_type="document_created",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"document": document.name, "area_id": str(document.area_id)},
    )
    return document



@router.get("/{document_id}", response_model=DocumentRead)
def get_document_detail(
    document_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DocumentRead:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentRead.model_validate(document, from_attributes=True)


@router.get("/{document_id}/signatures", response_model=List[DocumentSignatureInfo])
def list_document_signatures(
    document_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[DocumentSignatureInfo]:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    parties = list(document_service.list_parties(document))
    signature_rows = session.exec(
        select(Signature, SignatureRequest, WorkflowStep)
        .join(SignatureRequest, Signature.signature_request_id == SignatureRequest.id)
        .join(WorkflowStep, SignatureRequest.workflow_step_id == WorkflowStep.id)
        .join(WorkflowInstance, WorkflowStep.workflow_id == WorkflowInstance.id)
        .where(WorkflowInstance.document_id == document.id)
    ).all()

    signature_by_party: dict[UUID, Signature] = {}
    for signature, _request, step in signature_rows:
        if not step.party_id:
            continue
        current = signature_by_party.get(step.party_id)
        current_ts = current.signed_at if current and current.signed_at else datetime.min
        new_ts = signature.signed_at if signature.signed_at else datetime.min
        if step.party_id not in signature_by_party or new_ts >= current_ts:
            signature_by_party[step.party_id] = signature

    result: list[DocumentSignatureInfo] = []
    for party in sorted(parties, key=lambda p: p.order_index or 0):
        party_signature = signature_by_party.get(party.id)
        result.append(
            DocumentSignatureInfo(
                party_id=party.id,
                full_name=party.full_name,
                email=party.email,
                role=party.role,
                signature_method=party.signature_method,
                signature_type=party_signature.signature_type.value if party_signature else None,
                signed_at=party_signature.signed_at if party_signature else None,
                company_name=party.company_name,
                company_tax_id=party.company_tax_id,
                status=party.status,
                order_index=party.order_index,
            )
        )

    return result


@router.post("/{document_id}/parties", response_model=DocumentPartyRead, status_code=status.HTTP_201_CREATED)
def add_party(
    document_id: UUID,
    payload: DocumentPartyCreate,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> DocumentPartyRead:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    try:
        party = document_service.add_party(document, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_service.record_event(
        event_type="document_party_added",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"party_id": str(party.id), "role": party.role},
    )
    return _party_to_read(party)


@router.patch("/{document_id}/parties/{party_id}", response_model=DocumentPartyRead)
def update_party(
    document_id: UUID,
    party_id: UUID,
    payload: DocumentPartyUpdate,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> DocumentPartyRead:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    parties = document_service.list_parties(document)
    party = next((item for item in parties if item.id == party_id), None)
    if not party:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party not found")

    try:
        updated_party = document_service.update_party(party, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audit_service.record_event(
        event_type="document_party_updated",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={
            "party_id": str(updated_party.id),
            "channel": updated_party.notification_channel,
        },
    )
    return _party_to_read(updated_party)


@router.delete("/{document_id}/parties/{party_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_party(
    document_id: UUID,
    party_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> None:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    parties = document_service.list_parties(document)
    party = next((item for item in parties if item.id == party_id), None)
    if not party:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party not found")

    session.delete(party)
    session.commit()

    audit_service.record_event(
        event_type="document_party_removed",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"party_id": str(party.id)},
    )


@router.get("/{document_id}/parties", response_model=List[DocumentPartyRead])
def list_parties(
    document_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[DocumentPartyRead]:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    parties = document_service.list_parties(document)
    return [_party_to_read(item) for item in parties]


@router.post("/{document_id}/versions", response_model=DocumentVersionRead, status_code=status.HTTP_201_CREATED)
async def upload_version(
    document_id: UUID,
    request: Request,
    files: List[UploadFile] = File(...),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DocumentVersionRead:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum arquivo foi enviado.")

    try:
        version = await document_service.add_version(document, current_user.id, files)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    version_read = _build_version_read(session, document_service, document, version)
    audit_service.record_event(
        event_type="document_version_uploaded",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"version_id": str(version.id), "file": version.original_filename},
    )
    return version_read


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: UUID,
    payload: DocumentUpdate,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> DocumentRead:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    document = document_service.update_document(document, payload)
    audit_service.record_event(
        event_type="document_updated",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"status": document.status.value if hasattr(document.status, "value") else document.status},
    )
    return document


@router.post("/{document_id}/archive", response_model=DocumentRead)
def archive_document(
    document_id: UUID,
    payload: DocumentArchiveRequest,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> DocumentRead:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if payload.archived:
        updated_document = document_service.archive_document(document)
        event_type = "document_archived"
    else:
        updated_document = document_service.unarchive_document(document)
        event_type = "document_unarchived"
    audit_service.record_event(
        event_type=event_type,
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return updated_document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_route(
    document_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> None:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    audit_service.record_event(
        event_type="document_deleted",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    document_service.delete_document(document)


@router.get("/{document_id}/versions/{version_id}", response_model=DocumentVersionRead)
def get_document_version(
    document_id: UUID,
    version_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DocumentVersionRead:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return _build_version_read(session, document_service, document, version)


@router.get("/{document_id}/versions/{version_id}/content")
def get_document_version_content(
    document_id: UUID,
    version_id: UUID,
    download: bool = False,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    if not version.storage_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version file unavailable")

    storage = get_storage()
    try:
        pdf_bytes = storage.load_bytes(version.storage_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo n\u00e3o encontrado.") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao carregar o arquivo.") from exc

    filename = _resolve_signed_filename(version)
    disposition = "attachment" if download else "inline"
    media_type = version.mime_type or "application/pdf"
    return Response(
        pdf_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/{document_id}/versions/{version_id}/fields", response_model=List[DocumentFieldRead])
def list_document_fields(
    document_id: UUID,
    version_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[DocumentFieldRead]:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    fields = document_service.list_fields(document, version)
    return [DocumentFieldRead.model_validate(field, from_attributes=True) for field in fields]


@router.post(
    "/{document_id}/versions/{version_id}/fields",
    response_model=DocumentFieldRead,
    status_code=status.HTTP_201_CREATED,
)
def create_document_field(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentFieldCreate,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> DocumentFieldRead:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    try:
        field = document_service.create_field(document, version, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_service.record_event(
        event_type="document_field_created",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={
            "field_id": str(field.id),
            "role": field.role,
            "field_type": field.field_type,
        },
    )
    return DocumentFieldRead.model_validate(field, from_attributes=True)


@router.patch(
    "/{document_id}/versions/{version_id}/fields/{field_id}",
    response_model=DocumentFieldRead,
)
def update_document_field(
    document_id: UUID,
    version_id: UUID,
    field_id: UUID,
    payload: DocumentFieldUpdate,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> DocumentFieldRead:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    field = session.get(DocumentField, field_id)
    if not field or field.document_id != document.id or field.version_id != version.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    field = document_service.update_field(field, payload)
    audit_service.record_event(
        event_type="document_field_updated",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={
            "field_id": str(field.id),
            "field_type": field.field_type,
        },
    )
    return DocumentFieldRead.model_validate(field, from_attributes=True)


@router.delete("/{document_id}/versions/{version_id}/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_field(
    document_id: UUID,
    version_id: UUID,
    field_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> None:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    field = session.get(DocumentField, field_id)
    if not field or field.document_id != document.id or field.version_id != version.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    document_service.delete_field(field)
    audit_service.record_event(
        event_type="document_field_deleted",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"field_id": str(field_id)},
    )


@router.get("/{document_id}/versions/{version_id}/report")
def download_signed_report(
    document_id: UUID,
    version_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    try:
        pdf_bytes = _load_signed_pdf(version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    safe_pdf_name = _resolve_signed_filename(version)

    pkcs7_files = _load_pkcs7_files(version)
    bundle_name = Path(safe_pdf_name).stem or f"documento-{version.id}"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(safe_pdf_name, pdf_bytes)
        used_names: set[str] = {safe_pdf_name}
        for idx, (name, content) in enumerate(pkcs7_files, start=1):
            final_name = name
            if final_name in used_names:
                final_name = f"assinatura-{idx}.p7s"
            used_names.add(final_name)
            archive.writestr(final_name, content)
    zip_bytes = zip_buffer.getvalue()
    filename = f"{bundle_name}-assinaturas.zip"
    return Response(
        zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{document_id}/downloads/signed-pdf")
def download_signed_pdf(
    document_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = _get_latest_version(session, document)
    try:
        pdf_bytes = _load_signed_pdf(version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    safe_pdf_name = _resolve_signed_filename(version)
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_pdf_name}"'},
    )


@router.get("/{document_id}/downloads/signed-package", response_class=StreamingResponse)
def download_signed_package(
    document_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
) -> StreamingResponse:
    """
    Retorna um .zip contendo:
      - documento-assinado.pdf  (sempre que houver PDF final)
      - todos os arquivos .p7s encontrados na mesma pasta
    """
    service = DocumentService(session)
    document = service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    if document.status != DocumentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Documento ainda não está concluído.")

    if not document.current_version_id:
        raise HTTPException(status_code=404, detail="Documento não possui versão concluída.")

    version = session.get(DocumentVersion, document.current_version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Versão final não encontrada.")

    # Carrega PDF assinado
    try:
        pdf_bytes = _load_signed_pdf(version)
    except FileNotFoundError:
        pdf_bytes = b""

    # Carrega arquivos PKCS#7 (se existirem)
    pkcs7_files = _load_pkcs7_files(version)

    if not pdf_bytes and not pkcs7_files:
        raise HTTPException(status_code=404, detail="Nenhum artefato assinado encontrado.")

    # Monta o ZIP em memória
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        if pdf_bytes:
            archive.writestr("documento-assinado.pdf", pdf_bytes)

        for idx, (name, content) in enumerate(pkcs7_files, start=1):
            final_name = f"assinatura-{idx}.p7s"
            archive.writestr(final_name, content)

    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="documento-assinado-{document.id}.zip"'
        },
    )


@router.get("/{document_id}/downloads/p7s/{index}")
def download_signed_pkcs7(
    document_id: UUID,
    index: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    if index < 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signature artifact not found")
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = _get_latest_version(session, document)
    pkcs7_paths = _collect_pkcs7_paths(version)
    if index > len(pkcs7_paths):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signature artifact not found")
    file_path = Path(pkcs7_paths[index - 1])
    try:
        content = file_path.read_bytes()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signature artifact not available") from exc
    name = file_path.name or f"assinatura-{index}.p7s"
    if not name.lower().endswith(".p7s"):
        name = f"{name}.p7s"
    return Response(
        content,
        media_type="application/pkcs7-signature",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/{document_id}/signed-artifacts")
def get_signed_artifacts(
    document_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, object]:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    version = _get_latest_version(session, document)
    try:
        _load_signed_pdf(version)  # ensure PDF exists
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    pkcs7_files = _load_pkcs7_files(version)
    base_path = f"/api/v1/documents/{document_id}"
    pdf_url = f"{base_path}/downloads/signed-pdf"
    p7s_urls = [f"{base_path}/downloads/p7s/{idx}" for idx in range(1, len(pkcs7_files) + 1)]
    return {
        "pdf_url": pdf_url,
        "p7s_urls": p7s_urls,
        "has_digital_signature": bool(pkcs7_files),
    }


@router.get("/signing-agent/certificates", response_model=List[SigningCertificate])
def list_signing_agent_certificates(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[SigningCertificate]:
    del session  # not used but kept for future auditing context
    del current_user
    try:
        client = SigningAgentClient()
        raw_items = list(client.list_certificates())
    except SigningAgentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    certificates: List[SigningCertificate] = []
    for idx, item in enumerate(raw_items):
        if isinstance(item, dict):
            subject = item.get("subject") or item.get("Subject")
            issuer = item.get("issuer") or item.get("Issuer")
            serial = item.get("serialNumber") or item.get("serial") or item.get("SerialNumber")
            thumbprint = item.get("thumbprint") or item.get("Thumbprint")
            not_before = item.get("notBefore") or item.get("NotBefore")
            not_after = item.get("notAfter") or item.get("NotAfter")
            index = item.get("index", idx)
        else:
            # fallback for unexpected payloads
            subject = getattr(item, "subject", None)
            issuer = getattr(item, "issuer", None)
            serial = getattr(item, "serialNumber", None)
            thumbprint = getattr(item, "thumbprint", None)
            not_before = getattr(item, "notBefore", None)
            not_after = getattr(item, "notAfter", None)
            index = getattr(item, "index", idx)
        if not subject:
            continue
        certificates.append(
            SigningCertificate(
                index=int(index),
                subject=subject,
                issuer=issuer or "",
                serial_number=serial,
                thumbprint=thumbprint,
                not_before=not_before,
                not_after=not_after,
            ),
        )

    if not certificates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum certificado disponivel.")

    return certificates


@router.post(
    "/{document_id}/versions/{version_id}/sign-agent",
    response_model=SignPdfResponse,
)
def sign_document_version_with_agent(
    document_id: UUID,
    version_id: UUID,
    payload: SignPdfRequest,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> SignPdfResponse:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    return _execute_signing_agent(
        document_service=document_service,
        audit_service=audit_service,
        document=document,
        version=version,
        payload=payload,
        current_user=current_user,
        request=request,
    )


@router.get(
    "/{document_id}/versions/{version_id}/sign-agent/attempts/latest",
    response_model=Optional[SignAgentAttemptRead],
)
def get_latest_sign_agent_attempt(
    document_id: UUID,
    version_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> Optional[SignAgentAttemptRead]:
    document_service, _ = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    attempt = document_service.get_latest_signing_agent_attempt(document, version)
    if not attempt:
        return None

    return SignAgentAttemptRead.model_validate(attempt, from_attributes=True)


@router.post(
    "/{document_id}/versions/{version_id}/sign-agent/retry",
    response_model=SignPdfResponse,
)
def retry_sign_document_version_with_agent(
    document_id: UUID,
    version_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> SignPdfResponse:
    document_service, audit_service = _services(session)
    document = document_service.get_document(current_user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    version = session.get(DocumentVersion, version_id)
    if not version or version.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    attempt = document_service.get_latest_signing_agent_attempt(document, version)
    if not attempt or not attempt.payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No previous attempt to retry")

    try:
        payload = SignPdfRequest.model_validate(attempt.payload)
    except ValidationError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Dados anteriores do agente est\u00e3o incompletos para reenvio.",
                "attempt_id": str(attempt.id),
            },
        ) from exc

    return _execute_signing_agent(
        document_service=document_service,
        audit_service=audit_service,
        document=document,
        version=version,
        payload=payload,
        current_user=current_user,
        request=request,
    )
