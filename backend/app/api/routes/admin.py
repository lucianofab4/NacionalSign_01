from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.api.deps import get_db, get_current_active_user
from app.models.tenant import Area
from app.models.user import User
from app.schemas.workflow import WorkflowStepConfig, WorkflowTemplateCreate, WorkflowTemplateUpdate
from app.services.document import DocumentService
from app.services.workflow import WorkflowService

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def _workflow_service(session: Session) -> WorkflowService:
    return WorkflowService(session)


def _document_service(session: Session) -> DocumentService:
    return DocumentService(session)


@router.get("/templates")
def list_templates_page(
    request: Request,
    tenant_id: UUID,
    area_id: UUID | None = None,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # Restringir ADMIN e AREA_MANAGER apenas à sua área
    if current_user.profile in ["admin", "area_manager"]:
        user_area_id = getattr(current_user, "default_area_id", None)
        if not user_area_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Usuário não possui uma área padrão configurada.",
            )
        area_id = user_area_id
    
    workflow_service = _workflow_service(session)
    document_service = _document_service(session)

    workflow_templates = workflow_service.list_templates(
        tenant_id=tenant_id,
        area_id=area_id,
        include_inactive=True,
    )
    areas = session.exec(select(Area).where(Area.tenant_id == tenant_id)).all()
    area_lookup = {str(area.id): area.name for area in areas}
    documents = document_service.list_documents(tenant_id, area_id)

    message = request.query_params.get("message")
    error = request.query_params.get("error")

    if request.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(
            {
                "templates": [
                    {
                        "id": str(template.id),
                        "name": template.name,
                        "description": template.description,
                        "area_id": str(template.area_id),
                        "area_name": area_lookup.get(str(template.area_id)),
                        "is_active": template.is_active,
                        "steps": workflow_service._load_template_steps(template),
                    }
                    for template in workflow_templates
                ],
                "areas": [
                    {
                        "id": str(area.id),
                        "name": area.name,
                    }
                    for area in areas
                ],
                "documents": [
                    {
                        "id": str(document.id),
                        "name": document.name,
                        "area_id": str(document.area_id),
                        "area_name": area_lookup.get(str(document.area_id)),
                        "status": document.status.value if hasattr(document.status, "value") else document.status,
                    }
                    for document in documents
                ],
            }
        )

    return templates.TemplateResponse(
        request,
        "admin/templates.html",
        {
            "tenant_id": tenant_id,
            "areas": areas,
            "selected_area": area_id,
            "templates": workflow_templates,
            "area_lookup": area_lookup,
            "message": message,
            "error": error,
        },
    )


@router.post("/templates", response_class=HTMLResponse)
def handle_templates_actions(
    request: Request,
    action: str = Form(...),
    tenant_id: UUID = Form(...),
    area_id: UUID | None = Form(None),
    template_id: UUID | None = Form(None),
    name: str | None = Form(None),
    description: str | None = Form(None),
    steps_json: str | None = Form(None),
    duplicate_name: str | None = Form(None),
    target_area_id: UUID | None = Form(None),
    session: Session = Depends(get_db),
) -> HTMLResponse:
    workflow_service = _workflow_service(session)
    message = None
    error = None

    try:
        if action == "create":
            if not area_id:
                raise ValueError("Área é obrigatória para criar template")
            if not name:
                raise ValueError("Informe um nome para o template")
            raw_steps = json.loads(steps_json or "[]")
            if not raw_steps:
                raise ValueError("Adicione pelo menos uma etapa ao template")
            steps = [WorkflowStepConfig(**step) for step in raw_steps]
            payload = WorkflowTemplateCreate(
                area_id=area_id,
                name=name,
                description=description,
                steps=steps,
            )
            workflow_service.create_template(tenant_id, area_id, payload)
            message = "Template criado com sucesso."

        elif action == "duplicate":
            if not template_id or not duplicate_name:
                raise ValueError("Informe template e novo nome para duplicar")
            workflow_service.duplicate_template(
                tenant_id=tenant_id,
                template_id=template_id,
                name=duplicate_name,
                area_id=target_area_id,
            )
            message = "Template duplicado com sucesso."

        elif action == "update":
            if not template_id:
                raise ValueError("Template inválido")
            raw_steps = json.loads(steps_json or "[]")
            steps = [WorkflowStepConfig(**step) for step in raw_steps]
            payload = WorkflowTemplateUpdate(
                name=name,
                description=description,
                steps=steps,
            )
            workflow_service.update_template(tenant_id, template_id, payload)
            message = "Template atualizado com sucesso."

        elif action == "toggle":
            if not template_id:
                raise ValueError("Template inválido")
            template = workflow_service.get_template(template_id)
            if not template or template.tenant_id != tenant_id:
                raise ValueError("Template não encontrado")
            payload = WorkflowTemplateUpdate(is_active=not template.is_active)
            workflow_service.update_template(tenant_id, template_id, payload)
            message = "Template ativado." if not template.is_active else "Template desativado."

        elif action == "delete":
            if not template_id:
                raise ValueError("Template inválido")
            template = workflow_service.get_template(template_id)
            if not template or template.tenant_id != tenant_id:
                raise ValueError("Template não encontrado")
            session.delete(template)
            message = "Template excluído com sucesso."

        else:
            raise ValueError("Ação desconhecida")

        session.commit()
    except Exception as exc:  # pragma: no cover - flow handled via redirect
        session.rollback()
        error = str(exc)

    params = {"tenant_id": str(tenant_id)}
    if area_id:
        params["area_id"] = str(area_id)
    if message:
        params["message"] = message
    if error:
        params["error"] = error

    query = "&".join(f"{key}={value}" for key, value in params.items())
    return RedirectResponse(url=f"/admin/templates?{query}", status_code=303)


@router.post("/cleanup-deleted-documents", response_model=dict)
def cleanup_deleted_documents(
    days: int = 30,
    dry_run: bool = False,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Limpa documentos que estão na lixeira há mais de X dias.
    Requer usuário autenticado (endpoint admin).
    """
    from app.services.document import DocumentService
    from app.models.document import Document, DocumentStatus
    from datetime import timedelta
    
    if current_user.profile not in ["owner", "admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")
    
    document_service = DocumentService(session)
    
    if dry_run:
        # Modo dry-run: apenas contar
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        expired_documents = session.exec(
            select(Document)
            .where(Document.status == DocumentStatus.DELETED)
            .where(Document.deleted_at < cutoff_date)
        ).all()
        
        return {
            "success": True,
            "dry_run": True,
            "days": days,
            "documents_to_delete": len(expired_documents),
            "documents": [
                {
                    "id": str(doc.id),
                    "name": doc.name,
                    "deleted_at": doc.deleted_at.isoformat() if doc.deleted_at else None
                }
                for doc in expired_documents[:10]  # Mostrar apenas os primeiros 10
            ]
        }
    else:
        # Execução real
        deleted_count = document_service.cleanup_deleted_documents(days=days)
        return {
            "success": True,
            "dry_run": False,
            "days": days,
            "deleted_count": deleted_count,
            "message": f"{deleted_count} documentos excluídos permanentemente"
        }
