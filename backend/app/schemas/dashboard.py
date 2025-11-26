from pydantic import BaseModel


class DashboardMetrics(BaseModel):
    pending_for_user: int
    to_sign: int
    signed_in_area: int
    pending_in_area: int

