import os
from typing import Any, Generator

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.core.logging_setup import logger
from app.models.tenant import Area

def _build_connect_args(database_url: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        args["check_same_thread"] = False
    elif database_url.startswith("postgresql"):
        client_encoding = os.getenv("POSTGRES_CLIENT_ENCODING", "UTF8")
        args["options"] = f"-c client_encoding={client_encoding}"
    return args


def _create_engine(database_url: str):
    return create_engine(
        database_url,
        echo=settings.debug,
        future=True,
        connect_args=_build_connect_args(database_url),
        pool_pre_ping=True,
    )


def _test_connection(candidate_engine) -> None:
    with candidate_engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


def _collect_candidate_urls() -> list[str]:
    raw_candidates = [
        settings.database_url,
        settings.local_database_url,
        settings.database_fallback_url,
    ]
    candidates: list[str] = []
    for url in raw_candidates:
        cleaned = (url or "").strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def _resolve_engine():
    last_exc: Exception | None = None
    for candidate in _collect_candidate_urls():
        engine_candidate = _create_engine(candidate)
        try:
            _test_connection(engine_candidate)
            if candidate != settings.database_url:
                logger.warning(
                    "Banco primário indisponível (%s). Usando fallback: %s",
                    settings.database_url,
                    candidate,
                )
            logger.info("Banco de dados conectado: %s", candidate)
            return engine_candidate, candidate
        except Exception as exc:
            logger.error("Falha ao conectar em %s: %s", candidate, exc)
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Nenhum banco de dados configurado.")


engine, active_database_url = _resolve_engine()


def init_db() -> None:
    SQLModel.metadata.create_all(bind=engine)
    _ensure_schema_compatibility()
    _sanitize_initial_data()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def _sanitize_initial_data() -> None:
    with Session(engine) as session:
        areas = session.exec(select(Area)).all()
        dirty = False
        for area in areas:
            if area.description and not area.description.isascii():
                sanitized = area.description.encode("ascii", "ignore").decode("ascii").strip()
                area.description = sanitized or None
                session.add(area)
                dirty = True
        if dirty:
            session.commit()


def _ensure_schema_compatibility() -> None:
    """
    Keep backward compatibility with databases that were created before recent migrations.
    Currently ensures the optional phone_number column exists on users.
    """
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            table_names = set(inspector.get_table_names())
            if "users" in table_names:
                user_columns = {column["name"] for column in inspector.get_columns("users")}
                if "phone_number" not in user_columns:
                    logger.warning("Coluna 'phone_number' ausente na tabela 'users'. Aplicando ajuste automático.")
                    statement = "ALTER TABLE users ADD COLUMN phone_number VARCHAR(32)"
                    if active_database_url.startswith("postgresql"):
                        statement = "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(32)"
                    conn.exec_driver_sql(statement)
                    logger.info("Coluna 'phone_number' adicionada na tabela 'users'.")

                if "must_change_password" not in user_columns:
                    logger.warning(
                        "Coluna 'must_change_password' ausente na tabela 'users'. Aplicando ajuste automático."
                    )
                    statement = "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"
                    if active_database_url.startswith("postgresql"):
                        statement = (
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE"
                        )
                    conn.exec_driver_sql(statement)
                    logger.info("Coluna 'must_change_password' adicionada na tabela 'users'.")

            if "signatures" in table_names:
                signature_columns = {column["name"] for column in inspector.get_columns("signatures")}
                if "field_values" not in signature_columns:
                    logger.warning("Coluna 'field_values' ausente na tabela 'signatures'. Aplicando ajuste automático.")
                    statement = "ALTER TABLE signatures ADD COLUMN field_values JSON"
                    if active_database_url.startswith("postgresql"):
                        statement = "ALTER TABLE signatures ADD COLUMN IF NOT EXISTS field_values JSONB"
                    conn.exec_driver_sql(statement)
                    logger.info("Coluna 'field_values' adicionada na tabela 'signatures'.")
    except SQLAlchemyError as exc:  # pragma: no cover - best effort safeguard
        logger.error("Falha ao ajustar esquema do banco: %s", exc)
