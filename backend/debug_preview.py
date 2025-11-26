from pathlib import Path
from uuid import UUID
from sqlmodel import select
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from tests.conftest import register_and_login, auth_headers
from app.services.workflow import WorkflowService
from app.db.session import get_session
from app.services.storage import resolve_storage_root
from app.models.workflow import WorkflowStep, SignatureRequest

client = TestClient(app)
token, admin_email = register_and_login(client, 'debug@example.com', 'password123')
headers = auth_headers(token)
areas_resp = client.get(f"{settings.api_v1_str}/tenants/areas", headers=headers)
area_id = UUID(areas_resp.json()[0]['id'])
doc_resp = client.post(f"{settings.api_v1_str}/documents", json={'name': 'Contrato', 'area_id': str(area_id)}, headers=headers)
document_id = UUID(doc_resp.json()['id'])
client.post(f"{settings.api_v1_str}/documents/{document_id}/versions", files={'file': ('contrato.pdf', b'conteudo', 'application/pdf')}, headers=headers)
client.post(f"{settings.api_v1_str}/documents/{document_id}/parties", json={'full_name': 'Admin', 'email': admin_email, 'role': 'signer', 'order_index': 1}, headers=headers)
client.post(f"{settings.api_v1_str}/workflows/documents/{document_id}", json={'deadline_at': None}, headers=headers)

with next(get_session()) as session:
    flow = WorkflowService(session)
    step = session.exec(select(WorkflowStep).where(WorkflowStep.workflow_id != None)).first()
    request = session.exec(select(SignatureRequest).where(SignatureRequest.workflow_step_id == step.id)).first()
    token_value = flow.issue_signature_token(request.id)
    document = step.workflow.document
    version = session.get(document.__class__.versions.property.mapper.class_, document.current_version_id)
    print('storage_path:', version.storage_path)
    base = resolve_storage_root()
    p = Path(version.storage_path)
    print('absolute?', p.is_absolute())
    if not p.is_absolute():
        p = base / p
    print('path', p)
    print('exists', p.exists())
    resp = client.get(f"/public/signatures/{token_value}/preview")
    print('preview status', resp.status_code)
