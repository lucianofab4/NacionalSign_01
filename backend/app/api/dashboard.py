from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

@router.get("/metrics")
def get_metrics(area_id: str | None = None):
    # TODO: popular com dados reais
    return {
        "area_id": area_id,
        "documents_total": 0,
        "pending": 0,
        "completed": 0,
        "last_updated": "now"
    }
