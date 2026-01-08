# 🚀 NacionalSign - Sistema de Assinatura Digital

Sistema completo para gerenciamento e assinatura digital de documentos com suporte a certificados ICP-Brasil.

## 🎯 Recursos Principais
- ✅ **Assinatura Digital ICP-Brasil** - Certificados A1/A3 nativos
- ✅ **Multi-tenant Completo** - Empresas e áreas isoladas
- ✅ **Workflow Visual** - Templates arrastar-e-soltar
- ✅ **Auditoria LGPD** - Logs imutáveis com timestamp
- ✅ **Billing Automático** - Stripe, PagSeguro, planos
- ✅ **API REST Completa** - Documentação automática
- ✅ **Deploy Docker** - Produção em minutos

## 🏗️ Stack Tecnológica
- **Backend**: FastAPI + PostgreSQL + SQLModel
- **Frontend**: React + TypeScript + Vite  
- **Auth**: JWT + 2FA (TOTP)
- **Storage**: S3/MinIO compatível
- **Deploy**: Docker + Docker Compose
- **Signing**: Agente C# para certificados locais

## ⚡ Quick Start

### 1. Clone e Configure
```bash
git clone https://github.com/seu-usuario/nacionalsign.git
cd nacionalsign
cp .env.example .env
# ⚠️ EDITE .env com suas configurações
```

### 2. Docker (Recomendado)
```bash
docker-compose up -d
# Sistema rodando em http://localhost:8000
```

### 3. Desenvolvimento Local
```bash
# Backend
cd backend
poetry install && poetry run uvicorn app.main:app --reload

# Frontend  
cd frontend
npm install && npm run dev
```

## 🐳 Deploy Produção (DigitalOcean/VPS)

```bash
# 1. Na sua VM
git clone seu-repositorio
cd nacionalsign

# 2. Configurar ambiente
cp .env.example .env
# Configure DATABASE_URL, SECRET_KEY, SMTP, etc.

# 3. Subir produção
docker-compose up -d

# 4. SSL automático (opcional)
# Configure nginx ou Caddy para HTTPS
```

## 🔧 Environment Variables Críticas

```bash
# Segurança (MUDE!)
SECRET_KEY=sua-chave-super-secreta-aqui

# Database Produção
DATABASE_URL=postgresql://user:pass@localhost:5432/nacionalsign

# Email Notificações
SMTP_USERNAME=seu-email@gmail.com
SMTP_PASSWORD=sua-app-password

# Domínio Público
PUBLIC_BASE_URL=https://seudominio.com
```

## 📚 Funcionalidades Detalhadas
- SaaS billing, plan limits, and white-label customization per tenant.

## Architecture Overview
- **Frontend**: React + TypeScript + TailwindCSS (planned).
- **Backend**: FastAPI (Python) serving REST and async workers.
- **Database**: PostgreSQL for relational data and audit trails.
- **Queues & Cache**: Redis for background jobs and rate control.
- **File Storage**: S3-compatible object storage for originals and signed PDFs.
- **Infra**: Containerized services (Docker) with IaC (Terraform) planned for cloud environments.

## Module Breakdown
- Users & Areas: onboarding, 2FA, delegations (procuradores).
- Documents: upload, versioning, access controls, hashing.
- Workflows & Templates: drag-and-drop builder, reusable models, escalation rules.
- Signing & Audit: signature collection, timestamping, log export, verification portal.
- Billing & Administration: subscription plans, usage metrics, invoices.

## Roadmap (MVP)
1. UX/UI prototype (Figma).
2. Core API with authentication, tenants, areas, users.
3. Document upload pipeline and secure storage.
4. Workflow modeling and signature orchestration.
5. Audit trail, timestamp integration, public verification.
6. SaaS metering and payment gateway integration.
7. Security hardening, automated tests, and compliance review.

## Repository Structure
```
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── utils/
│   └── tests/
└── docs/
```


## Guia rápido de Deploy e Migração

### Backend
1. Instale dependências:
	```powershell
	cd backend
	python -m venv .venv
	.\.venv\Scripts\activate
	pip install -r requirements.txt
	```
2. Migre o banco de dados:
	```powershell
	alembic upgrade head
	```
3. Inicie o servidor:
	```powershell
	uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
	```
4. Backup manual:
	```powershell
	powershell -File ..\backup_script.ps1
	```

### Frontend
1. Instale dependências:
	```powershell
	cd frontend
	npm install
	```
2. Build:
	```powershell
	npm run build
	```
3. Servir frontend pelo backend (opcional):
	- Habilite `serve_frontend = true` no `.env` do backend.
	- O frontend será acessível em `/app`.

### Link opcional para o agente de assinatura
- Defina `SIGNING_AGENT_DOWNLOAD_URL` no `.env` do backend para anexar o link de download em todos os convites de assinatura enviados por e-mail.
- Defina `VITE_SIGNING_AGENT_DOWNLOAD_URL` no `.env` do frontend para exibir o mesmo link na página pública acessada pelos signatários.

### Outras rotinas
- Para reprocessar faturas automaticamente, agende o script do scheduler:
	```python
	from app.db.session import get_session
	from app.services.billing_scheduler import run_billing_scheduler
	session = get_session()
	run_billing_scheduler(session)
	```

### Migração de ambiente
- Sempre rode `alembic upgrade head` após atualizar o código.
- Para restaurar backup, use `pg_restore` e recupere os arquivos de documentos.


## Onboarding Rápido

1. Clone o repositório e siga os passos de deploy acima.
2. Crie um usuário admin via API ou seed inicial.
3. Acesse o frontend em `/app` após build.
4. Configure áreas, usuários e planos conforme sua empresa.
5. Faça upload de documentos e crie fluxos de assinatura.
6. Acompanhe faturas, limites e relatórios de auditoria.

## Exemplos de Uso da API

### Autenticação
```http
POST /api/v1/auth/login
{
	"username": "admin@empresa.com",
	"password": "senha"
}
```

### Criar Documento
```http
POST /api/v1/documents
{
	"name": "Contrato de Prestação",
	"area_id": "<uuid-da-area>"
}
```

### Listar Faturas
```http
GET /api/v1/billing/invoices
```

### Baixar relatório ICP
```http
GET /api/v1/documents/{document_id}/versions/{version_id}/report
```

## Dicas para Novos Usuários
- Use o painel de templates para criar fluxos reutilizáveis.
- Ative 2FA para administradores e usuários sensíveis.
- Consulte o log de auditoria para rastrear todas as ações.
- Em caso de erro, verifique os logs em `log/server.log`.
- Para dúvidas, consulte a documentação em `docs/` ou entre em contato com o suporte.
