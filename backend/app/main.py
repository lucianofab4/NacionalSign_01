from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI, status, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import FileResponse, RedirectResponse

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
from app.db.session import init_db
from app.core.logging_setup import logger


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Executa inicialização do banco ao iniciar a aplicação."""
    init_db()
    yield


def _normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().rstrip("/")
    return cleaned or None


def create_app() -> FastAPI:
    application = FastAPI(title=settings.project_name, debug=settings.debug, lifespan=lifespan)
    logger.info("NacionalSign API inicializada")

    # ===============================================================
    # CONFIGURAÇÃO DE CORS (ajuste definitivo)
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
        logger.warning("CORS origins não configurados; aplicando padrão %s", origins)

    logger.info(f"CORS configurado com origins: {origins}")

    # Middleware nativo do FastAPI para CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # 🔹 Middleware adicional para forçar CORS em todas as respostas (inclui erros)
    @application.middleware("http")
    async def add_cors_headers(request: Request, call_next):
        response = None
        try:
            response = await call_next(request)
        except Exception as exc:
            # captura erros para garantir que o CORS apareça mesmo em exceções
            logger.exception(f"[CORS FIX] Exceção durante a requisição: {exc}")
            response = JSONResponse(status_code=500, content={"detail": str(exc)})

        origin = request.headers.get("origin")
        if origin and any(origin.startswith(o) for o in origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Vary"] = "Origin"
        return response

    # 🔹 Handler global para OPTIONS (pré-flight)
    @application.options("/{rest_of_path:path}")
    async def preflight_handler(request: Request, rest_of_path: str):
        headers = {
            "Access-Control-Allow-Origin": request.headers.get("origin") or origins[0],
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
            "Access-Control-Allow-Credentials": "true",
        }
        return JSONResponse(content={"ok": True}, headers=headers)

    # ===============================================================
    # REGISTRO DE ROTAS
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
        """Redireciona o token público para o frontend correto."""
        target_base = settings.resolved_public_app_url() or (settings.public_base_url or "http://localhost:5173").rstrip("/")
        return RedirectResponse(
            url=f"{target_base}/public/sign/{token}",
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    # ===============================================================
    # TRATAMENTO GLOBAL DE EXCEÇÕES
    # ===============================================================
    import traceback

    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Erro não tratado: {exc}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    # ===============================================================
    # FRONTEND ESTÁTICO (opcional)
    # ===============================================================
    def ensure_frontend_build(frontend_directory: Path) -> bool:
        """Compila o frontend automaticamente se habilitado."""
        if not settings.auto_build_frontend:
            return frontend_directory.exists()
        dist_index = frontend_directory / "index.html"
        if dist_index.exists():
            return True
        src_dir = frontend_directory.parent
        if not src_dir.exists():
            logger.warning("Diretório do frontend não encontrado: %s", src_dir)
            return False
        logger.info("Compilando frontend em %s", src_dir)
        env = dict(**os.environ)
        try:
            if not (src_dir / "node_modules").exists() and (src_dir / "package.json").exists():
                logger.info("Instalando dependências do frontend...")
                subprocess.run(["npm", "install"], check=True, cwd=src_dir, env=env)
            subprocess.run(["npm", "run", "build"], check=True, cwd=src_dir, env=env)
            return dist_index.exists()
        except subprocess.CalledProcessError as exc:
            logger.exception("Falha ao compilar o frontend: %s", exc)
            return False

    frontend_enabled = False
    try:
        if getattr(settings, "serve_frontend", False):
            frontend_dir = Path(settings.frontend_dir).resolve()
            if frontend_dir.exists():
                ensure_frontend_build(frontend_dir)
                frontend_enabled = True

                assets_dir = frontend_dir / "assets"
                if assets_dir.exists():
                    application.mount(
                        "/assets",
                        StaticFiles(directory=str(assets_dir)),
                        name="frontend-assets",
                    )

                application.mount(
                    "/app",
                    StaticFiles(directory=str(frontend_dir), html=True),
                    name="frontend",
                )

                @application.get("/", include_in_schema=False)
                def frontend_root() -> RedirectResponse:
                    return RedirectResponse(url="/app", status_code=307)

                @application.get("/app", include_in_schema=False)
                def frontend_index() -> FileResponse:
                    return FileResponse(path=frontend_dir / "index.html")

                @application.get("/app/{full_path:path}", include_in_schema=False)
                def frontend_fallback(full_path: str) -> FileResponse:
                    return FileResponse(path=frontend_dir / "index.html")
            else:
                logger.warning("Diretório do frontend não encontrado: %s", frontend_dir)
    except Exception:
        logger.exception("Falha ao montar frontend estático")

    # ===============================================================
    # ROTA RAIZ PADRÃO
    # ===============================================================
    if not frontend_enabled:
        @application.get("/")
        def root() -> dict[str, str]:
            logger.info("Rota raiz acessada")
            return {"service": settings.project_name}

    return application


# ===============================================================
# PONTO DE ENTRADA
# ===============================================================
app = create_app()
