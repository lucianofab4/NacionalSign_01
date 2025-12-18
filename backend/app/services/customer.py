from __future__ import annotations

import secrets
from datetime import datetime
import secrets
import unicodedata
import re
from uuid import UUID

from sqlmodel import Session, select

from app.models.billing import Plan
from app.models.customer import Customer
from app.models.tenant import Tenant, Area
from app.models.user import User
from app.schemas.customer import CustomerCreate, CustomerUpdate
from app.services.storage import get_storage, normalize_storage_path
from app.utils.email_validation import normalize_deliverable_email
from app.utils.security import get_password_hash


class CustomerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_customers(self) -> list[Customer]:
        statement = select(Customer).order_by(Customer.created_at.desc())
        return list(self.session.exec(statement).all())

    def get_customer(self, customer_id: str | UUID) -> Customer | None:
        return self.session.get(Customer, UUID(str(customer_id)))

    def get_by_cnpj(self, cnpj: str) -> Customer | None:
        statement = select(Customer).where(Customer.cnpj == cnpj)
        return self.session.exec(statement).first()

    def get_by_activation_token(self, token: str) -> Customer | None:
        if not token:
            return None
        statement = select(Customer).where(Customer.activation_token == token)
        return self.session.exec(statement).first()

    def create_customer(self, payload: CustomerCreate) -> Customer:
        normalized_cnpj = ''.join(filter(str.isdigit, payload.cnpj))
        if self.get_by_cnpj(normalized_cnpj):
            raise ValueError("Customer with this CNPJ already exists")

        resolved_plan_id, resolved_quota = self._resolve_plan_and_quota(payload.plan_id, payload.document_quota)

        customer = Customer(
            corporate_name=payload.corporate_name,
            trade_name=payload.trade_name,
            cnpj=normalized_cnpj,
            responsible_name=payload.responsible_name,
            responsible_email=payload.responsible_email,
            responsible_phone=payload.responsible_phone,
            plan_id=resolved_plan_id,
            document_quota=resolved_quota,
            activation_token=self._generate_token(),
        )
        self.session.add(customer)
        self.session.commit()
        self.session.refresh(customer)
        return customer

    def update_customer(self, customer: Customer, payload: CustomerUpdate) -> Customer:
        update_data = payload.model_dump(exclude_unset=True)

        if "cnpj" in update_data and update_data["cnpj"]:
            new_cnpj = ''.join(filter(str.isdigit, str(update_data["cnpj"])) )
            if new_cnpj != customer.cnpj and self.get_by_cnpj(new_cnpj):
                raise ValueError("Customer with this CNPJ already exists")
            update_data["cnpj"] = new_cnpj

        if "plan_id" in update_data or "document_quota" in update_data:
            plan_id = update_data.get("plan_id", customer.plan_id)
            quota = update_data.get("document_quota", customer.document_quota)
            resolved_plan_id, resolved_quota = self._resolve_plan_and_quota(plan_id, quota)
            update_data["plan_id"] = resolved_plan_id
            update_data["document_quota"] = resolved_quota

        for field, value in update_data.items():
            setattr(customer, field, value)

        self.session.add(customer)
        self.session.commit()
        self.session.refresh(customer)
        return customer

    def generate_activation_token(self, customer: Customer) -> Customer:
        customer.activation_token = self._generate_token()
        self.session.add(customer)
        self.session.commit()
        self.session.refresh(customer)
        return customer

    def store_contract(self, customer: Customer, *, filename: str, content_type: str | None, data: bytes) -> Customer:
        storage = get_storage()
        storage_path = storage.save_bytes(
            root=f"customers/{customer.id}",
            name=filename,
            data=data,
        )
        customer.contract_storage_path = normalize_storage_path(storage_path)
        customer.contract_original_filename = filename
        customer.contract_mime_type = content_type or "application/octet-stream"
        customer.contract_uploaded_at = datetime.utcnow()
        self.session.add(customer)
        self.session.commit()
        self.session.refresh(customer)
        return customer

    def load_contract(self, customer: Customer) -> bytes:
        if not customer.contract_storage_path:
            raise ValueError("Contract not available")
        storage = get_storage()
        return storage.load_bytes(customer.contract_storage_path)

    # Activation helpers -------------------------------------------------
    def activate_customer(
        self,
        customer: Customer,
        *,
        password: str,
        full_name: str | None = None,
        email: str | None = None,
    ) -> tuple[Tenant, User]:
        if customer.tenant_id:
            raise ValueError("Customer already activated")
        admin_email_raw = (email or customer.responsible_email or "").strip()
        if not admin_email_raw:
            raise ValueError("Responsible email is required for activation")
        admin_email = normalize_deliverable_email(admin_email_raw)
        admin_name = (full_name or customer.responsible_name or "").strip()
        if not admin_name:
            raise ValueError("Responsible name is required for activation")
        tenant_name = customer.corporate_name or customer.trade_name or "Cliente NacionalSign"
        tenant_slug = self._generate_unique_slug(tenant_name)
        tenant = Tenant(
            name=tenant_name,
            slug=tenant_slug,
            cnpj=customer.cnpj,
            plan_id=str(customer.plan_id) if customer.plan_id else None,
            max_documents=customer.document_quota,
        )
        self.session.add(tenant)
        self.session.flush()

        default_area = Area(name="Geral", description="Área padrão", tenant_id=tenant.id)
        self.session.add(default_area)
        self.session.flush()

        admin_user = User(
            tenant_id=tenant.id,
            default_area_id=default_area.id,
            email=admin_email,
            cpf=customer.cnpj[:11].ljust(11, "0"),
            full_name=admin_name,
            password_hash=get_password_hash(password),
            profile="owner",
        )
        self.session.add(admin_user)

        customer.tenant_id = tenant.id
        customer.activation_token = None
        self.session.add(customer)

        self.session.commit()
        self.session.refresh(tenant)
        self.session.refresh(admin_user)
        return tenant, admin_user

    def _generate_unique_slug(self, base_name: str) -> str:
        slug = self._slugify(base_name)
        if not slug:
            slug = f"cliente-{secrets.token_hex(3)}"
        candidate = slug
        index = 1
        while self.session.exec(select(Tenant).where(Tenant.slug == candidate)).first() is not None:
            index += 1
            candidate = f"{slug}-{index}"
        return candidate

    @staticmethod
    def _slugify(value: str) -> str:
        value = (value or "").strip().lower()
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
        normalized = normalized.strip("-")
        normalized = re.sub(r"-{2,}", "-", normalized)
        return normalized

    def _resolve_plan_and_quota(
        self,
        plan_id: UUID | None,
        document_quota: int | None,
    ) -> tuple[UUID | None, int | None]:
        if plan_id is None:
            return None, document_quota
        plan = self.session.get(Plan, UUID(str(plan_id)))
        if not plan:
            raise ValueError("Plan not found")
        quota = document_quota if document_quota is not None else plan.document_quota
        return plan.id, quota

    @staticmethod
    def _generate_token() -> str:
        return secrets.token_urlsafe(24)

