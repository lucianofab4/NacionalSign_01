from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import engine
from app.core.logging_setup import logger

router = APIRouter(tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}


# ===============================================================
# 🚨 ROTA TEMPORÁRIA — PROMOVER USUÁRIO A OWNER (PÚBLICA)
# ===============================================================
@router.get("/_make_owner", include_in_schema=False)
def make_owner():
    email = "luciano.dias888@gmail.com"

    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET profile = 'owner' WHERE email = :email"),
            {"email": email},
        )

        if result.rowcount == 0:
            return {"status": "not_found", "email": email}

    logger.warning(f"[TEMP] Usuário promovido a owner: {email}")
    return {"status": "ok", "email": email}
