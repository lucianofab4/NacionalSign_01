from __future__ import annotations

from typing import Iterable
from uuid import UUID

from sqlmodel import Session, select

from app.models.tenant import Area, Tenant
from app.schemas.tenant import AreaCreate, AreaUpdate, TenantCreate


class TenantService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_tenant(self, payload: TenantCreate) -> Tenant:
        tenant = Tenant(**payload.model_dump())
        self.session.add(tenant)
        self.session.commit()
        self.session.refresh(tenant)
        return tenant

    def get_tenant(self, tenant_id: str | UUID) -> Tenant | None:
        return self.session.get(Tenant, tenant_id)

    def list_areas(self, tenant_id: str | UUID, include_inactive: bool = False) -> Iterable[Area]:
        tenant_uuid = UUID(str(tenant_id))
        statement = select(Area).where(Area.tenant_id == tenant_uuid)
        if not include_inactive:
            statement = statement.where(Area.is_active.is_(True))
        return self.session.exec(statement).all()

    def get_area(self, tenant_id: str | UUID, area_id: str | UUID) -> Area | None:
        tenant_uuid = UUID(str(tenant_id))
        area = self.session.get(Area, UUID(str(area_id)))
        if area and area.tenant_id == tenant_uuid:
            return area
        return None

    def create_area(self, tenant_id: str | UUID, payload: AreaCreate) -> Area:
        tenant_uuid = UUID(str(tenant_id))
        area = Area(tenant_id=tenant_uuid, **payload.model_dump())
        self.session.add(area)
        self.session.commit()
        self.session.refresh(area)
        return area

    def update_area(self, area: Area, payload: AreaUpdate) -> Area:
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(area, field, value)
        self.session.add(area)
        self.session.commit()
        self.session.refresh(area)
        return area