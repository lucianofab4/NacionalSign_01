from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.api.deps import get_current_active_user, get_db, require_roles
from app.models.document import Document, DocumentParty
from app.models.user import User, UserRole
from app.models.workflow import SignatureRequest, WorkflowInstance, WorkflowStep, WorkflowTemplate
from app.schemas.document import DocumentGroupRead
from app.schemas.workflow import (
    SignatureAction,
    SignatureRequestRead,
    WorkflowDispatch,
    WorkflowGroupDispatchResponse,
    WorkflowGroupResendResponse,
    WorkflowRead,
    WorkflowTemplateCreate,
    WorkflowTemplateDuplicate,
    WorkflowTemplateRead,
    WorkflowTemplateUpdate,
)
from app.core.config import settings
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.workflow import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _services(session: Session) -> tuple[WorkflowService, AuditService]:
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
    return WorkflowService(session, notification_service=notification_service), audit_service


def _require_area_manager_scope(current_user: User) -> UUID:
    area_id = getattr(current_user, "default_area_id", None)
    if not area_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não possui uma área padrão configurada.",
        )
    return area_id


def _enforce_template_permission(current_user: User, template: WorkflowTemplate) -> None:
    # Tanto ADMIN quanto AREA_MANAGER só podem acessar templates da sua área
    if current_user.profile in [UserRole.AREA_MANAGER.value, UserRole.ADMIN.value]:
        allowed_area = _require_area_manager_scope(current_user)
        if template.area_id != allowed_area:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Template não pertence à sua área.",
            )


def _template_response(service: WorkflowService, template) -> WorkflowTemplateRead:
    steps = service._load_template_steps(template)
    payload = {
        "id": template.id,
        "tenant_id": template.tenant_id,
        "area_id": template.area_id,
        "name": template.name,
        "description": template.description,
        "is_active": template.is_active,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "steps": [step.model_dump() for step in steps],
    }
    return WorkflowTemplateRead.model_validate(payload)


@router.get("/templates", response_model=List[WorkflowTemplateRead])
def list_templates(
    area_id: UUID | None = None,
    include_inactive: bool = False,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> List[WorkflowTemplateRead]:
    # Tanto ADMIN quanto AREA_MANAGER só veem templates da sua área
    if current_user.profile in [UserRole.AREA_MANAGER.value, UserRole.ADMIN.value]:
        area_id = _require_area_manager_scope(current_user)
    workflow_service, _ = _services(session)
    templates = workflow_service.list_templates(
        current_user.tenant_id,
        area_id,
        include_inactive=include_inactive,
    )
    return [_template_response(workflow_service, template) for template in templates]


@router.post("/templates", response_model=WorkflowTemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: WorkflowTemplateCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> WorkflowTemplateRead:
    # Tanto ADMIN quanto AREA_MANAGER só podem criar templates na sua área
    if current_user.profile in [UserRole.AREA_MANAGER.value, UserRole.ADMIN.value]:
        allowed_area = _require_area_manager_scope(current_user)
        if payload.area_id != allowed_area:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você só pode criar modelos para a sua área.",
            )
    workflow_service, audit_service = _services(session)
    template = workflow_service.create_template(current_user.tenant_id, payload.area_id, payload)
    audit_service.record_event(
        event_type="workflow_template_created",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        details={"template_id": str(template.id), "name": template.name},
    )
    return _template_response(workflow_service, template)


@router.get("/templates/{template_id}", response_model=WorkflowTemplateRead)
def get_template(
    template_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> WorkflowTemplateRead:
    print(f"🔍 DEBUG GET_TEMPLATE - User: {current_user.email} Profile: {current_user.profile}")
    workflow_service, _ = _services(session)
    template = workflow_service.get_template(template_id)
    if not template or template.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    _enforce_template_permission(current_user, template)
    return _template_response(workflow_service, template)


@router.put("/templates/{template_id}", response_model=WorkflowTemplateRead)
def update_template(
    template_id: UUID,
    payload: WorkflowTemplateUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> WorkflowTemplateRead:
    workflow_service, audit_service = _services(session)
    template = workflow_service.get_template(template_id)
    if not template or template.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    _enforce_template_permission(current_user, template)
    try:
        template = workflow_service.update_template(current_user.tenant_id, template_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    audit_service.record_event(
        event_type="workflow_template_updated",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        details={"template_id": str(template.id)},
    )
    return _template_response(workflow_service, template)


@router.post("/templates/{template_id}/duplicate", response_model=WorkflowTemplateRead, status_code=status.HTTP_201_CREATED)
def duplicate_template(
    template_id: UUID,
    payload: WorkflowTemplateDuplicate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> WorkflowTemplateRead:
    workflow_service, audit_service = _services(session)
    try:
        template = workflow_service.get_template(template_id)
    except ValueError:
        template = None
    if not template or template.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    _enforce_template_permission(current_user, template)

    target_area_id = payload.area_id or template.area_id
    # Tanto ADMIN quanto AREA_MANAGER só podem duplicar templates dentro da sua área
    if current_user.profile in [UserRole.AREA_MANAGER.value, UserRole.ADMIN.value]:
        allowed_area = _require_area_manager_scope(current_user)
        if target_area_id != allowed_area:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você só pode duplicar modelos dentro da sua área.",
            )

    try:
        template = workflow_service.duplicate_template(
            current_user.tenant_id,
            template_id,
            name=payload.name,
            area_id=target_area_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    audit_service.record_event(
        event_type="workflow_template_duplicated",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        details={"template_id": str(template.id), "source_template_id": str(template_id)},
    )
    return _template_response(workflow_service, template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> None:
    workflow_service, audit_service = _services(session)
    template = workflow_service.get_template(template_id)
    if not template or template.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    _enforce_template_permission(current_user, template)

    workflow_service.session.delete(template)
    workflow_service.session.commit()

    audit_service.record_event(
        event_type="workflow_template_deleted",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        details={"template_id": str(template_id)},
    )


@router.get("/documents/{document_id}", response_model=List[WorkflowRead])
def list_workflows(
    document_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[WorkflowRead]:
    workflow_service, _ = _services(session)
    workflows = workflow_service.list_workflows(document_id)
    return [
        workflow
        for workflow in workflows
        if session.get(Document, workflow.document_id).tenant_id == current_user.tenant_id
    ]


@router.post("/documents/{document_id}", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
def dispatch_workflow(
    document_id: UUID,
    payload: WorkflowDispatch,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> WorkflowRead:
    workflow_service, audit_service = _services(session)
    try:
        workflow = workflow_service.dispatch_workflow(current_user.tenant_id, document_id, payload)
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_service.record_event(
        event_type="workflow_dispatched",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=workflow.document_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"workflow_id": str(workflow.id)},
    )
    return workflow


@router.post("/documents/{document_id}/resend", status_code=status.HTTP_200_OK)
def resend_workflow_notifications(
    document_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, int]:
    workflow_service, _ = _services(session)
    try:
        notified = workflow_service.resend_pending_notifications(current_user.tenant_id, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"notified": notified}


@router.post(
    "/groups/{group_id}",
    response_model=WorkflowGroupDispatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def dispatch_group_workflow(
    group_id: UUID,
    payload: WorkflowDispatch,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> WorkflowGroupDispatchResponse:
    workflow_service, audit_service = _services(session)
    try:
        group, workflows = workflow_service.dispatch_group_workflow(current_user.tenant_id, group_id, payload)
    except ValueError as exc:
        detail = str(exc)
        error_status = (
            status.HTTP_404_NOT_FOUND if "n\u00e3o encontrado" in detail.lower() else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=error_status, detail=detail) from exc

    group_payload = DocumentGroupRead.model_validate(group, from_attributes=True)
    workflow_payloads = [WorkflowRead.model_validate(item, from_attributes=True) for item in workflows]

    audit_service.record_event(
        event_type="workflow_group_dispatched",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"group_id": str(group.id), "documents": len(workflow_payloads)},
    )

    return WorkflowGroupDispatchResponse(group=group_payload, workflows=workflow_payloads)


@router.post(
    "/groups/{group_id}/resend",
    response_model=WorkflowGroupResendResponse,
    status_code=status.HTTP_200_OK,
)
def resend_group_workflow_notifications(
    group_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> WorkflowGroupResendResponse:
    workflow_service, audit_service = _services(session)
    try:
        group, notified = workflow_service.resend_group_notifications(current_user.tenant_id, group_id)
    except ValueError as exc:
        detail = str(exc)
        error_status = (
            status.HTTP_404_NOT_FOUND if "n\u00e3o encontrado" in detail.lower() else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=error_status, detail=detail) from exc

    group_payload = DocumentGroupRead.model_validate(group, from_attributes=True)
    audit_service.record_event(
        event_type="workflow_group_notifications_resent",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=None,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"group_id": str(group.id), "notified": notified},
    )
    return WorkflowGroupResendResponse(group=group_payload, notified=notified)


@router.post("/signatures/{party_id}/share-link", status_code=status.HTTP_200_OK)
def issue_signature_share_link(
    party_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    party = session.get(DocumentParty, party_id)
    if not party:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participante n\u00e3o encontrado.")
    document = session.get(Document, party.document_id)
    if not document or document.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento n\u00e3o encontrado para o participante.")

    workflow = session.exec(
        select(WorkflowInstance)
        .where(WorkflowInstance.document_id == document.id)
        .order_by(WorkflowInstance.created_at.desc())
    ).first()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum fluxo encontrado para este participante.")

    step = session.exec(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == workflow.id)
        .where(WorkflowStep.party_id == party.id)
        .order_by(WorkflowStep.step_index.asc())
    ).first()
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhuma etapa associada a este participante.")

    signature_request = session.exec(
        select(SignatureRequest)
        .where(SignatureRequest.workflow_step_id == step.id)
        .order_by(SignatureRequest.created_at.desc())
    ).first()
    if not signature_request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum pedido de assinatura encontrado para este participante.")

    workflow_service, _ = _services(session)
    token = workflow_service.issue_signature_token(signature_request.id)
    session.commit()

    public_base = settings.resolved_public_app_url() or str(request.base_url).rstrip("/")
    url = f"{public_base}/public/sign/{token}"
    return {"token": token, "url": url}


@router.post("/signatures/{request_id}/actions", response_model=SignatureRequestRead)
def signature_action(
    request_id: UUID,
    payload: SignatureAction,
    request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> SignatureRequestRead:
    workflow_service, audit_service = _services(session)
    try:
        signature_request = workflow_service.record_signature_action(
            tenant_id=current_user.tenant_id,
            request_id=request_id,
            payload=payload,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    workflow = workflow_service.get_request_workflow(signature_request)
    document_id = workflow.document_id if workflow else None

    audit_service.record_event(
        event_type=f"signature_{payload.action}",
        actor_id=current_user.id,
        actor_role=current_user.profile,
        document_id=document_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={
            "request_id": str(signature_request.id),
            "status": signature_request.status.value,
        },
    )
    return signature_request
