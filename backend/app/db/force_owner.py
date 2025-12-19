from sqlalchemy import text
from app.db.session import engine
from app.core.logging_setup import logger

OWNER_EMAIL = "luciano.dias888@gmail.com"

def force_owner():
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
            logger.info(
                f"[FORCE_OWNER] linhas afetadas: {result.rowcount} para {OWNER_EMAIL}"
            )
    except Exception as e:
        logger.error(f"[FORCE_OWNER] erro ao forçar owner: {e}")
