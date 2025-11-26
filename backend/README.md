# Backend - NacionalSign

## Requisitos
- Python 3.11
- Poetry (ou pip)
- Docker e Docker Compose (opcional para ambiente local completo)

## Setup local
1. Copie `.env.example` para `.env` e ajuste variáveis.
2. Instale dependências:
   - Com Poetry: `poetry install`
3. (Opcional) Compilar o frontend para servir junto da API:
   ```bash
   cd ../frontend
   npm install
   npm run build
   cd ../backend
   ```
4. Execute a API:
   - Com Poetry: `SERVE_FRONTEND=true poetry run uvicorn app.main:app --reload`
   - A interface ficará disponível em `http://localhost:8000/` (redireciona para `/app`).
5. Docs: `http://localhost:8000/docs`.

## Testes
- `poetry run pytest -q`

## Docker Compose
- Sobe Postgres, MinIO e a API:
- `docker compose up --build`

Variáveis de ambiente principais no compose:
- `DATABASE_URL` (usa serviço `db`)
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` (MinIO)
- `S3_BUCKET_DOCUMENTS`
- `ALLOWED_ORIGINS` (ex.: `["http://localhost:5173"]`)

## Alembic (migrações)
- Gere migração (autogenerate) apontando para Postgres:
  - `poetry run alembic revision --autogenerate -m "initial schema"`
  - `poetry run alembic upgrade head`

Dica: defina `DATABASE_URL` no `.env` ou variável de ambiente ao rodar os comandos.

## Storage
- Por padrão salva em disco (pasta `storage`).
- Se `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` e `S3_BUCKET_DOCUMENTS` estiverem setados, usa S3/MinIO com URLs pré‑assinadas para download.

## Wallet (opcional)
- Ative `BILLING_USE_WALLET=true` para exigir saldo na criação de documento.
- Endpoints:
  - GET `/api/v1/billing/wallet`
  - POST `/api/v1/billing/wallet/credit`
