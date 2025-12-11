import os
from typing import Any, Generator

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.core.logging_setup import logger
from app.models.tenant import Area

connect_args: dict[str, Any] = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif settings.database_url.startswith("postgresql"):
    client_encoding = os.getenv("POSTGRES_CLIENT_ENCODING", "UTF8")
    connect_args["options"] = f"-c client_encoding={client_encoding}"

engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    connect_args=connect_args,
)


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
                    if settings.database_url.startswith("postgresql"):
                        statement = "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(32)"
                    conn.exec_driver_sql(statement)
                    logger.info("Coluna 'phone_number' adicionada na tabela 'users'.")

            if "signatures" in table_names:
                signature_columns = {column["name"] for column in inspector.get_columns("signatures")}
                if "field_values" not in signature_columns:
                    logger.warning("Coluna 'field_values' ausente na tabela 'signatures'. Aplicando ajuste automático.")
                    statement = "ALTER TABLE signatures ADD COLUMN field_values JSON"
                    if settings.database_url.startswith("postgresql"):
                        statement = "ALTER TABLE signatures ADD COLUMN IF NOT EXISTS field_values JSONB"
                    conn.exec_driver_sql(statement)
                    logger.info("Coluna 'field_values' adicionada na tabela 'signatures'.")
    except SQLAlchemyError as exc:  # pragma: no cover - best effort safeguard
        logger.error("Falha ao ajustar esquema do banco: %s", exc)
