import base64, io, os, uuid
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER
from app.main import app
from app.core.config import settings
from app.services.storage import resolve_storage_root
from pypdf import PdfReader

client = TestClient(app)

def make_pdf(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.drawString(100, 700, text)
    c.showPage()
    c.save()
    return buf.getvalue()

unique = uuid.uuid4().hex[:8]
email = f"{unique}@example.com"
password = "Senha123!"
payload = {
    "tenant_name": "Empresa Teste",
    "tenant_slug": f"empresa-{unique}",
    "admin_full_name": "Admin Teste",
    "admin_email": email,
    "admin_cpf": "12345678901",
    "admin_password": password,
}
reg = client.post(f"{settings.api_v1_str}/auth/register", json=payload)
assert reg.status_code == 201, reg.text
login = client.post(f"{settings.api_v1_str}/auth/login", json={"username": email, "password": password})
assert login.status_code == 200, login.text
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
areas = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
area_id = areas.json()[0]["id"]
doc = client.post(f"{settings.api_v1_str}/documents", json={"name": "Teste Unificado", "area_id": area_id}, headers=headers)
doc_id = doc.json()["id"]
file1 = make_pdf("Primeiro arquivo")
file2 = make_pdf("Segundo arquivo")
files = [
    ("files", ("primeiro.pdf", file1, "application/pdf")),
    ("files", ("segundo.pdf", file2, "application/pdf")),
]
resp = client.post(f"{settings.api_v1_str}/documents/{doc_id}/versions", files=files, headers=headers)
print("upload status", resp.status_code)
print(resp.json())
version_id = resp.json()["id"]
storage_path = resp.json()["storage_path"]
root = resolve_storage_root()
file_path = os.path.join(root, storage_path)
reader = PdfReader(file_path)
print("pages", len(reader.pages))
