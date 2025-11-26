from fastapi import status

from app.core.config import settings
from tests.conftest import auth_headers, register_and_login


def test_update_me_endpoint(client):
    token, _ = register_and_login(
        client,
        email="user-settings@example.com",
        password="SenhaForte123",
    )

    response = client.patch(
        f"{settings.api_v1_str}/users/me",
        json={"full_name": "Usuário Atualizado"},
        headers=auth_headers(token),
    )

    assert response.status_code == status.HTTP_200_OK, response.json()
    body = response.json()
    assert body["full_name"] == "Usuário Atualizado"
