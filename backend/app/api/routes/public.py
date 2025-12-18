import base64
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_db
from app.core.config import settings
from app.services.storage import get_storage, resolve_storage_root
from app.models.document import AuditArtifact, Document, DocumentField, DocumentParty, DocumentVersion
from app.models.workflow import (
    Signature,
    SignatureRequest,
    SignatureRequestStatus,
    WorkflowInstance,
    WorkflowStep,
)
from app.schemas.customer import (
    CustomerActivationComplete,
    CustomerActivationCompleteResponse,
    CustomerActivationStatus,
)
from app.schemas.public import (
    PublicCertificateSignPayload,
    PublicSignatureAction,
    PublicSignatureMeta,
    PublicSignatureRead,
    VerificationRead,
    VerificationSigner,
    VerificationWorkflow,
)
from app.schemas.workflow import SignatureAction
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.customer import CustomerService
from app.services.workflow import WorkflowService

router = APIRouter(prefix="/public", tags=["public"])
templates = Jinja2Templates(directory="app/templates")
CONSENT_TEXT_DEFAULT = "Autorizo o uso da minha imagem e dados pessoais para fins de assinatura eletrônica."
CONSENT_VERSION_DEFAULT = "v1"

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



@router.get("/customers/activate/{token}", response_model=CustomerActivationStatus)
def get_customer_activation(token: str, session: Session = Depends(get_db)) -> CustomerActivationStatus:
    service = CustomerService(session)
    customer = service.get_by_activation_token(token)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link de ativação inválido.")
    return CustomerActivationStatus(
        corporate_name=customer.corporate_name,
        trade_name=customer.trade_name,
        responsible_name=customer.responsible_name,
        responsible_email=customer.responsible_email,
        plan_id=customer.plan_id,
        document_quota=customer.document_quota,
        activated=bool(customer.tenant_id),
        tenant_id=customer.tenant_id,
    )


@router.post("/customers/activate/{token}", response_model=CustomerActivationCompleteResponse)
def complete_customer_activation(
    token: str,
    payload: CustomerActivationComplete,
    session: Session = Depends(get_db),
) -> CustomerActivationCompleteResponse:
    service = CustomerService(session)
    customer = service.get_by_activation_token(token)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link de ativação inválido.")
    if customer.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Este cliente já foi ativado.")
    try:
        tenant, user = service.activate_customer(
            customer,
            password=payload.password,
            full_name=payload.admin_full_name,
            email=payload.admin_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    login_base = settings.resolved_public_app_url() or (settings.public_base_url or "http://localhost:5173").rstrip("/")
    login_url = f"{login_base}/" if login_base else "/"
    return CustomerActivationCompleteResponse(
        tenant_id=tenant.id,
        user_id=user.id,
        login_url=login_url,
    )


def _build_public_asset_urls(token: str) -> tuple[str, str]:
    base_preview_path = f"/public/signatures/{token}/preview"
    configured_base = (settings.public_base_url or "").rstrip("/")
    if configured_base:
        preview_url = f"{configured_base}{base_preview_path}"
    else:
        preview_url = base_preview_path
    download_url = f"{preview_url}?download=1"
    return preview_url, download_url

def _resolve_signature_method(party: DocumentParty | None) -> str:
    if not party or not getattr(party, "signature_method", None):
        return "electronic"
    method = party.signature_method.strip().lower()
    if method not in {"digital", "electronic"}:
        return "electronic"
    return method


def _collect_field_rules(session: Session, document: Document, party: DocumentParty | None) -> dict[str, object]:
    role = (party.role.strip().lower() if party and party.role else "")
    if not role:
        return {
            "typed_name_required": False,
            "signature_image_required": False,
            "field_types": [],
        }
    fields = session.exec(
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


def _build_public_signature_summary(
    session: Session,
    document: Document,
    party: DocumentParty | None,
    request: SignatureRequest,
    signature: Signature | None,
) -> tuple[PublicSignatureRead, UUID | None]:
    require_email_confirmation = bool(party and party.require_email and getattr(party, "email", None))
    require_phone_confirmation = bool(party and party.require_phone and getattr(party, "phone_number", None))
    version_id = getattr(document, "current_version_id", None)
    version = session.get(DocumentVersion, version_id) if version_id else None
    if not version:
        version = session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.created_at.desc())
        ).first()
        version_id = version.id if version else version_id
    mime_type = (version.mime_type or "").lower() if version and version.mime_type else ""
    supports_certificate = bool(version and ("pdf" in mime_type))
    field_rules = _collect_field_rules(session, document, party)
    allow_typed_name = bool(party and party.allow_typed_name)
    allow_signature_image = bool(party and party.allow_signature_image)
    typed_required = bool(field_rules.get("typed_name_required"))
    image_required = bool(field_rules.get("signature_image_required"))
    signature_method = _resolve_signature_method(party)
    requires_certificate = signature_method == "digital"
    if not requires_certificate:
        requires_certificate = supports_certificate and not (
            allow_typed_name or allow_signature_image or typed_required or image_required
        )

    summary = PublicSignatureRead(
        document_name=document.name,
        signer_name=party.full_name if party else "",
        status=request.status.value,
        expires_at=request.token_expires_at,
        can_sign=request.status in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT},
        reason=signature.reason if signature else None,
        requires_email_confirmation=require_email_confirmation,
        requires_phone_confirmation=require_phone_confirmation,
        supports_certificate=supports_certificate,
        requires_certificate=requires_certificate,
        signature_method=signature_method,
    )
    return summary, version_id


def _build_signature_template_context(
    document: Document,
    party: DocumentParty | None,
    sig_request: SignatureRequest,
    signature_entry: Signature | None,
    field_rules: dict[str, object],
) -> dict[str, object]:
    typed_name_required = bool(field_rules.get("typed_name_required"))
    signature_image_required = bool(field_rules.get("signature_image_required"))
    available_fields = field_rules.get("field_types") or []

    allow_typed_name = bool(party and party.allow_typed_name)
    allow_signature_image = bool(party and party.allow_signature_image)

    collect_typed_name = allow_typed_name or typed_name_required
    collect_signature_image = allow_signature_image or signature_image_required
    signature_method_label = (party.signature_method or "electronic").strip().lower() if party else "electronic"
    requires_cpf_confirmation = signature_method_label.startswith("digital") and bool(getattr(party, "cpf", None))

    require_email_confirmation = bool(party and party.require_email and getattr(party, "email", None))
    require_phone_confirmation = bool(party and party.require_phone and getattr(party, "phone_number", None))

    return {
        "document_name": document.name,
        "signer_name": party.full_name if party else "",
        "status": sig_request.status.value,
        "expires_at": sig_request.token_expires_at,
        "can_sign": sig_request.status in {SignatureRequestStatus.PENDING, SignatureRequestStatus.SENT},
        "reason": signature_entry.reason if signature_entry else None,
        "allow_typed_name": allow_typed_name,
        "collect_typed_name": collect_typed_name,
        "typed_name_required": typed_name_required and collect_typed_name,
        "allow_signature_image": allow_signature_image,
        "collect_signature_image": collect_signature_image,
        "signature_image_required": signature_image_required and collect_signature_image,
        "collect_email_confirmation": require_email_confirmation,
        "collect_phone_confirmation": require_phone_confirmation,
        "requires_consent": allow_signature_image,
        "consent_text": CONSENT_TEXT_DEFAULT,
        "consent_version": CONSENT_VERSION_DEFAULT,
        "available_fields": available_fields,
        "requires_cpf_confirmation": requires_cpf_confirmation,
    }



def _build_verification(session: Session, document_id: UUID) -> VerificationRead:
    document = session.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    version = session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None

    parties = session.exec(
        select(DocumentParty)
        .where(DocumentParty.document_id == document.id)
        .order_by(DocumentParty.order_index)
    ).all()

    workflows = session.exec(
        select(WorkflowInstance)
        .where(WorkflowInstance.document_id == document.id)
        .order_by(WorkflowInstance.created_at.desc())
    ).all()

    signer_items: list[VerificationSigner] = []
    for party in parties:
        result = session.exec(
            select(SignatureRequest, WorkflowStep)
            .join(WorkflowStep, SignatureRequest.workflow_step_id == WorkflowStep.id)
            .where(WorkflowStep.party_id == party.id)
            .order_by(SignatureRequest.created_at.desc())
        ).first()

        request_obj: SignatureRequest | None = None
        step_obj: WorkflowStep | None = None
        if result:
            request_obj, step_obj = result

        signature_obj: Signature | None = None
        if request_obj:
            signature_obj = session.exec(
                select(Signature)
                .where(Signature.signature_request_id == request_obj.id)
                .order_by(Signature.created_at.desc())
            ).first()

        status = request_obj.status.value if request_obj else SignatureRequestStatus.PENDING.value
        action = step_obj.action if step_obj else "sign"
        completed_at = step_obj.completed_at if step_obj else None
        signed_at = signature_obj.signed_at if signature_obj else None
        reason = signature_obj.reason if signature_obj else None

        signer_items.append(
            VerificationSigner(
                party_id=party.id,
                full_name=party.full_name,
                email=party.email,
                role=party.role,
                action=action,
                status=status,
                signed_at=signed_at,
                completed_at=completed_at,
                reason=reason,
            )
        )

    workflow_items: list[VerificationWorkflow] = []
    for workflow in workflows:
        steps = session.exec(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.step_index)
        ).all()
        steps_total = len(steps)
        steps_completed = sum(1 for step in steps if step.completed_at)

        workflow_items.append(
            VerificationWorkflow(
                workflow_id=workflow.id,
                status=workflow.status.value,
                started_at=workflow.started_at,
                completed_at=workflow.completed_at,
                steps_total=steps_total,
                steps_completed=steps_completed,
            )
        )

    download_url: str | None = None
    report_url: str | None = None
    version_filename: str | None = None
    version_size: int | None = None

    if version:
        download_url = f"/public/verification/{document.id}/download"
        version_filename = version.original_filename
        version_size = version.size_bytes

    report_artifact = session.exec(
        select(AuditArtifact)
        .where(AuditArtifact.document_id == document.id)
        .where(AuditArtifact.artifact_type == "final_report")
    ).first()
    if report_artifact:
        report_url = f"/public/verification/{document.id}/report"

    return VerificationRead(
        document_id=document.id,
        name=document.name,
        status=document.status.value,
        hash=version.sha256 if version else None,
        version_id=version.id if version else None,
        version_filename=version_filename,
        version_size=version_size,
        download_url=download_url,
        report_url=report_url,
        updated_at=document.updated_at,
        signers=signer_items,
        workflows=workflow_items,
    )


@router.get("/verification/{document_id}", response_model=VerificationRead)
def verify_document(document_id: UUID, session: Session = Depends(get_db)) -> VerificationRead:
    return _build_verification(session, document_id)


@router.get("/verification/{document_id}/page", response_class=HTMLResponse)
def verify_document_page(
    document_id: UUID,
    session: Session = Depends(get_db),
) -> HTMLResponse:
    verification = _build_verification(session, document_id)
    template = templates.get_template("public/verification.html")
    content = template.render(verification=verification)
    return HTMLResponse(content)


@router.get("/verification/{document_id}/download")
def download_document(document_id: UUID, session: Session = Depends(get_db)) -> FileResponse:
    document = session.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.current_version_id:
        raise HTTPException(status_code=404, detail="No document version available")

    version = session.get(DocumentVersion, document.current_version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Document version missing")

    file_path = Path(version.storage_path)
    if not file_path.is_absolute():
        file_path = resolve_storage_root() / file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on storage")

    media_type = version.mime_type or "application/octet-stream"
    return FileResponse(path=file_path, media_type=media_type, filename=version.original_filename)


@router.get("/verification/{document_id}/report")
def download_report(document_id: UUID, session: Session = Depends(get_db)) -> FileResponse:
    document = session.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    artifact = session.exec(
        select(AuditArtifact)
        .where(AuditArtifact.document_id == document.id)
        .where(AuditArtifact.artifact_type == "final_report")
    ).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Report not available")

    file_path = Path(artifact.storage_path)
    if not file_path.is_absolute():
        file_path = resolve_storage_root() / file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report file missing")

    return FileResponse(path=file_path, media_type="application/pdf", filename="relatorio-final.pdf")


@router.get("/signatures/{token}/page", response_class=HTMLResponse)
def signature_page(token: str, request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    workflow_service = _build_workflow_service(session)
    try:
        data = workflow_service.get_public_signature(token)
    except ValueError:
        template = templates.get_template("public/signature.html")
        content = template.render(
            request=request,
            token=token,
            error="Token inválido ou expirado.",
            signature=None,
            form_data={"typed_name": "", "confirm_email": "", "confirm_phone_last4": "", "confirm_cpf": ""},
        )
        return HTMLResponse(content, status_code=status.HTTP_404_NOT_FOUND)

    document = data["document"]
    party = data["party"]
    sig_request = data["request"]
    signature_entry = data["signature"]
    field_rules = _collect_field_rules(session, document, party)

    signature_summary = _build_signature_template_context(document, party, sig_request, signature_entry, field_rules)

    template = templates.get_template("public/signature.html")
    content = template.render(
        request=request,
        token=token,
        signature=signature_summary,
        error=None,
        message=None,
        form_data={"typed_name": "", "confirm_email": "", "confirm_phone_last4": "", "confirm_cpf": ""},
    )
    return HTMLResponse(content)


@router.get("/signatures/{token}/preview")
def signature_preview(token: str, download: bool = False, session: Session = Depends(get_db)) -> Response:
    workflow_service = _build_workflow_service(session)
    try:
        data = workflow_service.get_public_signature(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    document = data["document"]
    version_id = getattr(document, "current_version_id", None)
    version = session.get(DocumentVersion, version_id) if version_id else None
    if not version:
        version = session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.created_at.desc())
        ).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versão inexistente")

    storage = get_storage()
    try:
        pdf_bytes = storage.load_bytes(version.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo não localizado")

    media_type = version.mime_type or "application/pdf"
    filename = version.original_filename or "documento.pdf"
    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{filename}"'}
    return Response(content=pdf_bytes, media_type=media_type, headers=headers)

@router.post("/signatures/{token}/sign-with-certificate", response_model=PublicSignatureRead)
def public_sign_with_certificate(
    token: str,
    payload: PublicCertificateSignPayload,
    request: Request,
    session: Session = Depends(get_db),
) -> PublicSignatureRead:
    workflow_service = _build_workflow_service(session)
    try:
        data = workflow_service.get_public_signature(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    document = data["document"]
    party = data["party"]
    request_obj = data["request"]
    signature_entry = data["signature"]

    summary_before, _ = _build_public_signature_summary(session, document, party, request_obj, signature_entry)
    if not summary_before.supports_certificate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assinatura com certificado nao suportada.")
    if not summary_before.requires_certificate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta assinatura deve ser eletrônica.")

    signature_payload = SignatureAction(
        action="sign",
        token=token,
        signature_type="digital",
        typed_name=payload.typed_name,
        confirm_email=payload.confirm_email,
        confirm_phone_last4=payload.confirm_phone_last4,
        confirm_cpf=payload.confirm_cpf,
        certificate_subject=payload.certificate_subject,
        certificate_issuer=payload.certificate_issuer,
        certificate_serial=payload.certificate_serial,
        certificate_thumbprint=payload.certificate_thumbprint,
        signature_protocol=payload.signature_protocol,
    )
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        updated_request = workflow_service.record_public_signature_action(
            token,
            signature_payload,
            ip=ip,
            user_agent=user_agent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    signature_record = session.exec(
        select(Signature)
        .where(Signature.signature_request_id == updated_request.id)
        .order_by(Signature.created_at.desc())
    ).first()

    summary_after, _ = _build_public_signature_summary(session, document, party, updated_request, signature_record)
    summary_after = summary_after.copy(update={"can_sign": False})
    return summary_after

@router.post("/signatures/{token}/page", response_class=HTMLResponse)
async def act_on_signature_page(
    token: str,
    request: Request,
    action: str = Form(...),
    reason: str | None = Form(None),
    typed_name: str | None = Form(None),
    confirm_email: str | None = Form(None),
    confirm_phone_last4: str | None = Form(None),
    confirm_cpf: str | None = Form(None),
    consent: str | None = Form(None),
    consent_text: str | None = Form(None),
    consent_version: str | None = Form(None),
    signature_image: UploadFile | None = File(None),
    session: Session = Depends(get_db),
) -> HTMLResponse:
    workflow_service = _build_workflow_service(session)
    error: str | None = None
    message: str | None = None

    try:
        data = workflow_service.get_public_signature(token)
    except ValueError:
        template = templates.get_template("public/signature.html")
        content = template.render(
            request=request,
            token=token,
            error="Token inválido ou expirado.",
            signature=None,
            message=None,
            form_data={"typed_name": "", "confirm_email": "", "confirm_phone_last4": "", "confirm_cpf": ""},
        )
        return HTMLResponse(content, status_code=status.HTTP_404_NOT_FOUND)

    document = data["document"]
    party = data["party"]
    sig_request = data["request"]
    field_rules = _collect_field_rules(session, document, party)

    typed_name_value = typed_name.strip() if typed_name else None
    confirm_email_value = confirm_email.strip() if confirm_email else None
    confirm_phone_value = confirm_phone_last4.strip() if confirm_phone_last4 else None
    confirm_cpf_value = confirm_cpf.strip() if confirm_cpf else None
    form_data = {
        "typed_name": typed_name_value or "",
        "confirm_email": confirm_email_value or "",
        "confirm_phone_last4": confirm_phone_value or "",
        "confirm_cpf": confirm_cpf_value or "",
    }
    consent_given = (consent or "").strip().lower() in {"1", "true", "yes", "on"}
    consent_version_value = (consent_version or CONSENT_VERSION_DEFAULT).strip() or CONSENT_VERSION_DEFAULT
    consent_text_value = (
        (consent_text.strip() if consent_text else CONSENT_TEXT_DEFAULT) if consent_given else None
    )

    image_b64: str | None = None
    image_mime: str | None = None
    image_name: str | None = None
    if signature_image is not None:
        file_bytes = await signature_image.read()
        if file_bytes:
            image_b64 = base64.b64encode(file_bytes).decode("ascii")
            image_mime = signature_image.content_type
            image_name = signature_image.filename

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    try:
        signature_payload = SignatureAction(
            action=action,
            reason=reason,
            token=token,
            typed_name=typed_name_value,
            signature_image=image_b64,
            signature_image_mime=image_mime,
            signature_image_name=image_name,
            consent=consent_given,
            consent_text=consent_text_value,
            consent_version=consent_version_value,
            confirm_email=confirm_email_value,
            confirm_phone_last4=confirm_phone_value,
            confirm_cpf=confirm_cpf_value,
        )
        updated_request = workflow_service.record_public_signature_action(
            token,
            signature_payload,
            ip=ip,
            user_agent=user_agent,
        )
        sig_request = updated_request
        message = "Assinatura registrada com sucesso." if action == "sign" else "Recusa registrada com sucesso."
    except ValueError as exc:
        error = str(exc)
        sig_request = session.get(SignatureRequest, sig_request.id)

    signature_entry = session.exec(
        select(Signature)
        .where(Signature.signature_request_id == sig_request.id)
        .order_by(Signature.created_at.desc())
    ).first()

    signature_summary = _build_signature_template_context(document, party, sig_request, signature_entry, field_rules)

    template = templates.get_template("public/signature.html")
    content = template.render(
        request=request,
        token=token,
        error=error,
        message=message,
        signature=signature_summary,
        form_data=form_data,
    )
    status_code = status.HTTP_200_OK if not error else status.HTTP_400_BAD_REQUEST
    return HTMLResponse(content, status_code=status_code)

