import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)
unique = uuid.uuid4().hex[:8]
email = f"{unique}@example.com"
payload = {
    "tenant_name": "Empresa Teste",
    "tenant_slug": f"empresa-{unique}",
    "admin_full_name": "Admin Teste",
    "admin_email": email,
    "admin_cpf": "12345678901",
    "admin_password": "Senha123!",
}
reg = client.post(f"{settings.api_v1_str}/auth/register", json=payload)
print('register', reg.status_code)
login = client.post(f"{settings.api_v1_str}/auth/login", json={"username": email, "password": "Senha123!"})
print('login', login.status_code)
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
doc = client.get(f"{settings.api_v1_str}/documents", headers=headers)
print(doc.status_code)
print(doc.json())
