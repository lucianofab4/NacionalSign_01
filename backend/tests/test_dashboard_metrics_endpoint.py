from fastapi import status

from app.core.config import settings
from app.schemas.dashboard import DashboardMetrics
from tests.conftest import auth_headers, register_and_login


def test_dashboard_metrics_requires_auth(client):
    response = client.get(f"{settings.api_v1_str}/dashboard/metrics")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_dashboard_metrics_returns_counts(client):
    token, _ = register_and_login(client, "metrics@example.com", "StrongPass!123")
    response = client.get(
        f"{settings.api_v1_str}/dashboard/metrics",
        headers=auth_headers(token),
    )
    assert response.status_code == status.HTTP_200_OK
    payload = DashboardMetrics(**response.json())
    assert payload.pending_for_user >= 0
    assert payload.to_sign >= 0
    assert payload.signed_in_area >= 0
    assert payload.pending_in_area >= 0
