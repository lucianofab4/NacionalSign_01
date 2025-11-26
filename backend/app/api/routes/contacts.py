from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.deps import get_current_active_user, get_db
from app.models.contact import Contact
from app.schemas.contact import ContactRead
from app.services.contact import ContactService
from app.models.user import User

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactRead])
def search_contacts(
    q: str = Query(""),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[ContactRead]:
    service = ContactService(session)
    contacts = service.search(current_user.tenant_id, q.strip(), limit)
    return [ContactRead.model_validate(contact, from_attributes=True) for contact in contacts]


@router.get("/{contact_id}", response_model=ContactRead)
def get_contact(
    contact_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ContactRead:
    contact = session.get(Contact, contact_id)
    if not contact or contact.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return ContactRead.model_validate(contact, from_attributes=True)
