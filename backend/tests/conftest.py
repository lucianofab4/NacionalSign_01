from __future__ import annotations

import os
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.db import session as db_session_module
from app.db.session import get_session
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture()
def db_engine(tmp_path):
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if not test_database_url:
        db_path = tmp_path / f"test_{uuid.uuid4().hex}.db"
        test_database_url = f"sqlite:///{db_path}"

    is_postgres = test_database_url.startswith("postgresql")

    admin_engine = None
    schema_name = None

    if is_postgres:
        url = make_url(test_database_url)
        schema_name = f"test_{uuid.uuid4().hex}"
        admin_engine = create_engine(test_database_url, future=True)
        with admin_engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
            )
        client_encoding = os.getenv("POSTGRES_CLIENT_ENCODING", "UTF8")
        connect_args = {"options": f"-csearch_path={schema_name},public -cclient_encoding={client_encoding}"}
        engine = create_engine(test_database_url, connect_args=connect_args, future=True)
    else:
        engine = create_engine(test_database_url, connect_args={"check_same_thread": False})

    SQLModel.metadata.create_all(bind=engine)

    original_engine = db_session_module.engine
    original_get_session = db_session_module.get_session

    db_session_module.engine = engine

    def _get_session():
        with Session(engine) as session:
            yield session

    db_session_module.get_session = _get_session

    def override_dependency():
        yield from _get_session()

    app.dependency_overrides[get_session] = override_dependency

    yield engine

    app.dependency_overrides.pop(get_session, None)
    db_session_module.get_session = original_get_session
    db_session_module.engine = original_engine
    engine.dispose()
    if is_postgres and admin_engine and schema_name:
        with admin_engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
            )
        admin_engine.dispose()


@pytest.fixture()
def storage_env(monkeypatch, tmp_path) -> None:
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("NACIONALSIGN_STORAGE", str(storage_dir))
    yield


@pytest.fixture()
def client(db_engine, storage_env) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def db_session(db_engine) -> Session:
    with Session(db_engine) as session:
        yield session


def register_and_login(client: TestClient, email: str, password: str) -> tuple[dict[str, str], str]:
    unique_email = f"{uuid.uuid4().hex[:8]}_{email}"
    payload = {
        "tenant_name": "Empresa Teste",
        "tenant_slug": f"empresa-{uuid.uuid4().hex[:8]}",
        "admin_full_name": "Admin Teste",
        "admin_email": unique_email,
        "admin_cpf": "12345678900",
        "admin_password": password,
    }
    register_response = client.post(f"{settings.api_v1_str}/auth/register", json=payload)
    assert register_response.status_code == status.HTTP_201_CREATED, register_response.json()

    login_response = client.post(
        f"{settings.api_v1_str}/auth/login",
        json={"username": unique_email, "password": password},
    )
    assert login_response.status_code == status.HTTP_200_OK, login_response.json()
    token = login_response.json()
    return token, unique_email


def auth_headers(token: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {token['access_token']}"}
