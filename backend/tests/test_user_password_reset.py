from uuid import UUID

from fastapi import status
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.user import User
from .conftest import auth_headers, register_and_login


def test_admin_can_reset_user_password(client: TestClient, db_session: Session) -> None:
    token, admin_email = register_and_login(client, email="admin@example.com", password="Admin123!")
    headers = auth_headers(token)

    areas_response = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
    assert areas_response.status_code == status.HTTP_200_OK, areas_response.json()
    areas = areas_response.json()
    default_area_id = areas[0]["id"] if areas else None

    new_user_email = "luciano.dias888@example.com"
    original_password = "OrigPwd123!"
    create_payload = {
        "email": new_user_email,
        "cpf": "12345678901",
        "full_name": "Luciano Dias",
        "phone_number": "+55 11 99999-0000",
        "password": original_password,
        "default_area_id": default_area_id,
        "profile": "user",
    }
    create_response = client.post(
        f"{settings.api_v1_str}/users",
        headers=headers,
        json=create_payload,
    )
    assert create_response.status_code == status.HTTP_201_CREATED, create_response.json()
    created_user = create_response.json()
    user_id = created_user["id"]

    db_user = db_session.get(User, UUID(user_id))
    assert db_user is not None
    previous_hash = db_user.password_hash

    reset_response = client.post(
        f"{settings.api_v1_str}/users/{user_id}/reset-password",
        headers=headers,
    )
    assert reset_response.status_code == status.HTTP_200_OK, reset_response.json()
    payload = reset_response.json()
    assert payload["user_id"] == user_id
    assert payload["email"] == new_user_email
    temporary_password = payload["temporary_password"]
    assert len(temporary_password) >= 12

    db_session.expire_all()
    updated_user = db_session.get(User, UUID(user_id))
    assert updated_user is not None
    assert updated_user.password_hash != previous_hash

    # Old password should fail
    old_login = client.post(
        f"{settings.api_v1_str}/auth/login",
        json={"username": new_user_email, "password": original_password},
    )
    assert old_login.status_code == status.HTTP_401_UNAUTHORIZED

    # Temporary password should succeed
    temp_login = client.post(
        f"{settings.api_v1_str}/auth/login",
        json={"username": new_user_email, "password": temporary_password},
    )
    assert temp_login.status_code == status.HTTP_200_OK, temp_login.json()

    # Audit log should be recorded
    audit_rows = db_session.exec(
        select(AuditLog).where(AuditLog.event_type == "user_password_reset")
    ).all()
    assert any(row.details.get("target_user_id") == user_id for row in audit_rows)
