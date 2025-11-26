from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db, require_roles
from app.models.user import User, UserRole
from app.schemas.tenant import AreaCreate, AreaRead, AreaUpdate, TenantCreate, TenantRead
from pydantic import BaseModel
from app.services.tenant import TenantService
router = APIRouter(prefix="/tenants", tags=["tenants"])

class TenantUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    cnpj: str | None = None
    theme: str | None = None
    max_users: int | None = None
    max_documents: int | None = None
    custom_logo_url: str | None = None

@router.patch('/{tenant_id}', response_model=TenantRead)
def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> TenantRead:
    service = TenantService(session)
    tenant = service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tenant, field, value)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreate, session: Session = Depends(get_db)) -> TenantRead:
    service = TenantService(session)
    return service.create_tenant(payload)


@router.get("/me", response_model=TenantRead)
def get_my_tenant(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> TenantRead:
    service = TenantService(session)
    tenant = service.get_tenant(current_user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("/areas", response_model=List[AreaRead])
def list_areas(
    include_inactive: bool = False,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> List[AreaRead]:
    service = TenantService(session)
    return list(service.list_areas(current_user.tenant_id, include_inactive=include_inactive))


@router.post("/areas", response_model=AreaRead, status_code=status.HTTP_201_CREATED)
def create_area(
    payload: AreaCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> AreaRead:
    service = TenantService(session)
    return service.create_area(current_user.tenant_id, payload)


@router.patch("/areas/{area_id}", response_model=AreaRead)
def update_area(
    area_id: str,
    payload: AreaUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> AreaRead:
    service = TenantService(session)
    area = service.get_area(current_user.tenant_id, area_id)
    if not area:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found")
    return service.update_area(area, payload)


@router.delete("/areas/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_area(
    area_id: str,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    service = TenantService(session)
    area = service.get_area(current_user.tenant_id, area_id)
    if not area:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Area not found")
    service.update_area(area, AreaUpdate(is_active=False))