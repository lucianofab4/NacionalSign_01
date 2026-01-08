from __future__ import annotations

from typing import Iterable
from uuid import UUID

from sqlmodel import Session, select

from app.models.tenant import Area
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.utils.email_validation import normalize_deliverable_email
from app.utils.security import get_password_hash, generate_secure_password


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_users(self, tenant_id: str | UUID) -> Iterable[User]:
        tenant_uuid = UUID(str(tenant_id))
        statement = select(User).where(User.tenant_id == tenant_uuid)
        return self.session.exec(statement).all()

    def get_user(self, user_id: str | UUID) -> User | None:
        return self.session.get(User, UUID(str(user_id)))

    def create_user(self, tenant_id: str | UUID, payload: UserCreate) -> User:
        tenant_uuid = UUID(str(tenant_id))
        area_id = self._validate_area(payload.default_area_id, tenant_uuid)

        try:
            normalized_email = normalize_deliverable_email(payload.email)
        except ValueError as exc:
            raise ValueError("E-mail inválido") from exc
        normalized_cpf = payload.cpf.strip() if payload.cpf else ""
        if not normalized_cpf:
            normalized_cpf = None

        existing_email = self.session.exec(
            select(User).where(User.email == normalized_email).where(User.tenant_id == tenant_uuid)
        ).first()
        if existing_email:
            raise ValueError("Já existe um usuário com este e-mail.")

        if normalized_cpf:
            existing_cpf = self.session.exec(
                select(User).where(User.cpf == normalized_cpf).where(User.tenant_id == tenant_uuid)
            ).first()
            if existing_cpf:
                raise ValueError("Já existe um usuário com este CPF.")

        user = User(
            tenant_id=tenant_uuid,
            email=normalized_email,
            cpf=normalized_cpf,
            full_name=payload.full_name,
            phone_number=payload.phone_number.strip() if payload.phone_number else None,
            password_hash=get_password_hash(payload.password),
            profile=payload.profile.value,
            default_area_id=area_id,
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def update_user(self, tenant_id: str | UUID, user: User, payload: UserUpdate) -> User:
        tenant_uuid = UUID(str(tenant_id))
        if user.tenant_id != tenant_uuid:
            raise ValueError("User does not belong to tenant")

        update_data = payload.model_dump(exclude_unset=True)
        if "password" in update_data:
            update_data["password_hash"] = get_password_hash(update_data.pop("password"))
            update_data["must_change_password"] = False
        if "profile" in update_data and update_data["profile"] is not None:
            update_data["profile"] = update_data["profile"].value
        if "default_area_id" in update_data and update_data["default_area_id"] is not None:
            update_data["default_area_id"] = self._validate_area(update_data["default_area_id"], tenant_uuid)
        if "phone_number" in update_data and update_data["phone_number"] is not None:
            update_data["phone_number"] = update_data["phone_number"].strip()

        for field, value in update_data.items():
            setattr(user, field, value)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def update_user_settings(
        self,
        user: User,
        payload_full_name: str | None = None,
        payload_phone_number: str | None = None,
        payload_password: str | None = None,
        payload_two_factor: bool | None = None,
        payload_default_area: UUID | None = None,
    ) -> User:
        update_map: dict[str, object] = {}
        if payload_full_name is not None:
            update_map["full_name"] = payload_full_name
        if payload_phone_number is not None:
            update_map["phone_number"] = payload_phone_number.strip() if payload_phone_number else None
        if payload_password:
            update_map["password_hash"] = get_password_hash(payload_password)
            update_map["must_change_password"] = False
        if payload_two_factor is not None:
            update_map["two_factor_enabled"] = payload_two_factor
        if payload_default_area is not None:
            update_map["default_area_id"] = self._validate_area(payload_default_area, user.tenant_id)

        for field, value in update_map.items():
            setattr(user, field, value)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def deactivate_user(self, user: User) -> User:
        user.is_active = False
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def reset_user_password(
        self,
        *,
        user: User,
        actor_tenant_id: str | UUID,
        password_length: int = 14,
    ) -> str:
        tenant_uuid = UUID(str(actor_tenant_id))
        if user.tenant_id != tenant_uuid:
            raise ValueError("User does not belong to tenant")
        temporary_password = generate_secure_password(password_length)
        user.password_hash = get_password_hash(temporary_password)
        user.must_change_password = True
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return temporary_password

    def _validate_area(self, area_id: str | UUID | None, tenant_uuid: UUID) -> UUID | None:
        if area_id is None:
            return None
        area = self.session.get(Area, UUID(str(area_id)))
        if not area or area.tenant_id != tenant_uuid:
            raise ValueError("Area does not belong to tenant")
        return area.id
