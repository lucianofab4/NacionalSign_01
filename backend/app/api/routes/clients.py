from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.deps import get_db, require_roles
from app.core.config import settings
from app.models.client import Client
from app.models.user import User, UserRole
from app.schemas.client import ClientCreate, ClientRead

router = APIRouter(prefix="/clients", tags=["clients"])


def _build_portal_url(token: uuid4) -> str:
    base = settings.resolved_public_app_url() or "http://localhost:5173"
    return f"{base}/portal/{token}"


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> ClientRead:
    tenant_id = current_user.tenant_id
    name_exists = session.exec(
        select(Client).where(Client.tenant_id == tenant_id).where(Client.name == payload.name.strip())
    ).first()
    if name_exists:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Client already exists")

    portal_token = uuid4()
    client = Client(
        tenant_id=tenant_id,
        name=payload.name.strip(),
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        notes=payload.notes,
        portal_token=portal_token,
        portal_url=_build_portal_url(portal_token),
    )
    session.add(client)
    session.commit()
    session.refresh(client)
    return ClientRead.model_validate(client)


@router.get("", response_model=list[ClientRead])
def list_clients(
    session: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AREA_MANAGER)),
) -> list[ClientRead]:
    clients = session.exec(select(Client).where(Client.tenant_id == current_user.tenant_id)).all()
    return [ClientRead.model_validate(item) for item in clients]
