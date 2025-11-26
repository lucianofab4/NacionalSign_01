from __future__ import annotations

from fastapi import status

from app.core.config import settings
from tests.conftest import auth_headers, register_and_login  # type: ignore


def test_wallet_get_and_credit(client):
    token, _ = register_and_login(client, email="admin@example.com", password="secret123")

    # Get wallet (default 0)
    resp_get = client.get(f"{settings.api_v1_str}/billing/wallet", headers=auth_headers(token))
    assert resp_get.status_code == status.HTTP_200_OK, resp_get.text
    data = resp_get.json()
    assert data["balance_cents"] >= 0

    # Credit wallet
    resp_credit = client.post(
        f"{settings.api_v1_str}/billing/wallet/credit",
        json={"amount_cents": 1234},
        headers=auth_headers(token),
    )
    assert resp_credit.status_code == status.HTTP_201_CREATED, resp_credit.text
    data2 = resp_credit.json()
    assert data2["balance_cents"] >= 1234
