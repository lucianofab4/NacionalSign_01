from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import RedirectResponse
from sqlalchemy import text

from app.api.routes import (
    admin,
    audit,
    auth,
    billing,
    clients,
    contacts,
    customers,
    dashboard,
    documents,
    health,
    public,
    public_signatures,
    tenants,
    users,
    workflows,
)
from app.core.config import settings
from app.db.session import init_db, engine
from app.core.logging_setup import logger


OWNER_EMAIL = "luciano.dias888@gmail.com"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    # Inicializa banco / tabelas
    init_db()

    # 🔥 FORÇA O OWNER SEMPRE QUE O APP SOBE (RENDER FREE SAFE)
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE users
                    SET profile = 'owner'
                    WHERE lower(email) = :email
                    """
                ),
                {"email": OWNER_EMAIL.lower()},
            )
            logger.warning(
                f"[BOOTSTRAP OWNER] linhas afetadas={result.rowcount} email={OWNER_EMAIL}"
            )
    except Exception as exc:
        logger.error(f"[BOOTSTRAP OWNER] erro ao forçar owner: {exc}")

    yield


def _normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().rstrip("/")
    return cleaned or None


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.project_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    logger.info("NacionalSign API inicializada")

    # ===============================================================
    # CORS
    # ===============================================================
    public_front_base = settings.resolved_public_app_url()
    extra_origins = [_normalize_origin(public_front_base)] if public_front_base else []
    raw_origins = settings.allowed_origins + extra_origins

    origins: list[str] = []
    for item in raw_origins:
        normalized = _normalize_origin(item)
        if normalized and normalized not in origins:
            origins.append(normalized)

    if not origins:
        origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://nacionalsign-01-yll1.onrender.com",
        ]

    logger.info(f"CORS configurado com origins: {origins}")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # ===============================================================
    # Middleware extra de CORS
    # ===============================================================
    @application.middleware("http")
    async def add_cors_headers(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception(f"[CORS FIX] Exceção durante a requisição: {exc}")
            response = JSONResponse(status_code=500, content={"detail": str(exc)})

        origin = request.headers.get("origin")
        if origin and any(origin.startswith(o) for o in origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            requested_headers = request.headers.get("access-control-request-headers")
            allowed_headers = requested_headers or "Authorization, Content-Type, X-Requested-With, Accept, Origin"
            response.headers["Access-Control-Allow-Headers"] = allowed_headers
            response.headers["Vary"] = "Origin"
        return response

    @application.options("/{rest_of_path:path}")
    async def preflight_handler(request: Request, rest_of_path: str):
        headers = {
            "Access-Control-Allow-Origin": request.headers.get("origin") or origins[0],
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": request.headers.get(
                "access-control-request-headers",
                "Authorization, Content-Type, X-Requested-With, Accept, Origin",
            ),
            "Access-Control-Allow-Credentials": "true",
        }
        return JSONResponse(content={"ok": True}, headers=headers)

    # ===============================================================
    # ROTAS
    # ===============================================================
    application.include_router(health.router, prefix="/health")
    application.include_router(admin.router, prefix="/admin")
    application.include_router(audit.router, prefix=settings.api_v1_str)
    application.include_router(auth.router, prefix=settings.api_v1_str)
    application.include_router(tenants.router, prefix=settings.api_v1_str)
    application.include_router(users.router, prefix=settings.api_v1_str)
    application.include_router(clients.router, prefix=settings.api_v1_str)
    application.include_router(contacts.router, prefix=settings.api_v1_str)
    application.include_router(customers.router, prefix=settings.api_v1_str)
    application.include_router(dashboard.router, prefix=settings.api_v1_str)
    application.include_router(documents.router, prefix=settings.api_v1_str)
    application.include_router(workflows.router, prefix=settings.api_v1_str)
    application.include_router(billing.router, prefix=settings.api_v1_str)
    application.include_router(public_signatures.router, prefix="")
    application.include_router(public.router, prefix="")

    # ===============================================================
    # REDIRECIONAMENTO PARA ASSINATURA PÚBLICA
    # ===============================================================
    @application.get("/public/sign/{token}", include_in_schema=False)
    def public_sign_entry(token: str) -> RedirectResponse:
        target_base = (
            settings.resolved_public_app_url()
            or settings.public_base_url
            or "http://localhost:5173"
        ).rstrip("/")

        return RedirectResponse(
            url=f"{target_base}/public/sign/{token}",
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    # ===============================================================
    # ROTA RAIZ
    # ===============================================================
    @application.get("/")
    def root():
        return {"service": settings.project_name}

    return application


app = create_app()
