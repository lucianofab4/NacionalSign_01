from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlmodel import Session

from app.api.deps import get_db, require_roles
from app.core.config import settings
from app.models.customer import Customer
from app.models.user import UserRole, User
from app.schemas.customer import CustomerActivationLink, CustomerCreate, CustomerRead, CustomerUpdate
from app.services.customer import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


def _service(session: Session) -> CustomerService:
    return CustomerService(session)


def _serialize_customer(customer: Customer) -> CustomerRead:
    download_url: str | None = None
    base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else ""
    if customer.contract_storage_path:
        download_url = f"{base_url}/api/v1/customers/{customer.id}/contract" if base_url else f"/api/v1/customers/{customer.id}/contract"
    read = CustomerRead.model_validate(customer, from_attributes=True)
    return read.model_copy(update={
        "contract_file_name": customer.contract_original_filename,
        "contract_download_url": download_url,
    })

def _require_customer_admin(
    current_user: User = Depends(require_roles(UserRole.OWNER)),
) -> User:
    allowed = {
        email.strip().lower()
        for email in (settings.customer_admin_emails or [])
        if isinstance(email, str) and email.strip()
    }
    if allowed:
        user_email = (current_user.email or "").strip().lower()
        if user_email not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return current_user

@router.get("", response_model=List[CustomerRead])
def list_customers(
    session: Session = Depends(get_db),
    current_user: User = Depends(_require_customer_admin),
) -> List[CustomerRead]:
    service = _service(session)
    customers = service.list_customers()
    return [_serialize_customer(customer) for customer in customers]


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(_require_customer_admin),
) -> CustomerRead:
    service = _service(session)
    try:
        customer = service.create_customer(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _serialize_customer(customer)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(_require_customer_admin),
) -> CustomerRead:
    service = _service(session)
    customer = service.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return _serialize_customer(customer)


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    session: Session = Depends(get_db),
    current_user: User = Depends(_require_customer_admin),
) -> CustomerRead:
    service = _service(session)
    customer = service.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    try:
        updated = service.update_customer(customer, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _serialize_customer(updated)


@router.post("/{customer_id}/generate-link", response_model=CustomerActivationLink)
def generate_activation_link(
    customer_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(_require_customer_admin),
) -> CustomerActivationLink:
    service = _service(session)
    customer = service.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    updated = service.generate_activation_token(customer)
    if not updated.activation_token:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate activation token")
    front_base = settings.resolved_public_app_url()
    fallback_base = (settings.public_base_url or "http://localhost:5173").rstrip("/")
    target_base = front_base or fallback_base
    activation_url = f"{target_base}/activate/{updated.activation_token}" if target_base else updated.activation_token
    return CustomerActivationLink(activation_token=updated.activation_token, activation_url=activation_url)


@router.post("/{customer_id}/contract", response_model=CustomerRead)
async def upload_contract(
    customer_id: UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    current_user: User = Depends(_require_customer_admin),
) -> CustomerRead:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")
    service = _service(session)
    customer = service.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    updated = service.store_contract(customer, filename=file.filename, content_type=file.content_type, data=data)
    return _serialize_customer(updated)


@router.get("/{customer_id}/contract")
def download_contract(
    customer_id: UUID,
    session: Session = Depends(get_db),
    current_user: User = Depends(_require_customer_admin),
) -> Response:
    service = _service(session)
    customer = service.get_customer(customer_id)
    if not customer or not customer.contract_storage_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")
    try:
        data = service.load_contract(customer)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    filename = customer.contract_original_filename or "contract.pdf"
    media_type = customer.contract_mime_type or "application/octet-stream"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\""
    }
    return Response(content=data, media_type=media_type, headers=headers)
