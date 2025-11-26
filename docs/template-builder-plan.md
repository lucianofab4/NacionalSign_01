# Template Builder – Plano de Evolução

## Objetivo
Criar uma UI avançada (React) para montagem de fluxos de assinatura reutilizáveis, com suporte a múltiplos papéis, canais (e-mail/SMS), prazos e validações. A experiência deve permitir arrastar/ordenar etapas, editar campos in-place, pré-visualizar responsabilidades e salvar rapidamente no backend (`/admin/templates`).

## Escopo
1. **Visual Builder** (drag & drop)
   - Coluna de *step palette* com papéis sugeridos (signer, approver, witness, procurator).
   - Canvas central com lista ordenável de etapas (drag para reordenar).
   - Config panel à direita com campos: `role`, `action`, `execution`, `deadline_hours`, `notification_channel`, `two_factor_type` (futuro).
   - Validação visual (ex.: falta e-mail para canal `email`).

2. **Integração API**
   - Listagem (`GET /admin/templates?tenant_id=...&area_id=...`).
   - Criação/edição (`POST /admin/templates`, `PATCH /workflow/templates/{id}`).
   - Duplicação/ativação via endpoints existentes.
   - Preview (`GET /workflow/templates/{id}`) para carregar builder.

3. **UX Complementar**
   - Filtros por área e busca por nome.
   - Feedback (toast) em operações CRUD.
   - Export/import JSON de steps.
   - Indicação de canais por cor (email=azul, sms=verde).

4. **Arquitetura Frontend (React)**
   - Stack proposta: `Vite + React + TypeScript`, `Tailwind` para estilização rápida, `React DnD` ou `@dnd-kit` para drag & drop.
   - `zustand` ou `Redux Toolkit` para estado do builder.
   - `React Query` para cache de templates.

## Roadmap
1. **Setup Frontend**
   - Criar pasta `frontend/`, inicializar Vite (React + TS).
   - Configurar client HTTP com `axios` e env (`VITE_API_BASE_URL`).

2. **MVP Builder**
   - Página `/templates` com lista (fetch + tabela).
   - Modal/rota `/templates/new` com builder básico (adicionar/remover steps, salvar via API).
   - Upload de steps em JSON (fallback).

3. **Drag & Drop + Paleta**
   - Implementar reorder com `dnd-kit`.
   - Paleta lateral com botões de papéis pré-configurados.
   - Painel de edição detalhado (inputs controlados).

4. **Validações & UX**
   - Regras de canal (ex.: `sms` exige `phone_number` no party).
   - Exibir warnings quando template inclui papéis ausentes no documento.
   - Preview do e-mail/SMS gerado (futuro).

5. **Integração Backend Futuras**
   - Endpoint para sugerir papéis com base no documento (`GET /documents/{id}/parties`).
   - Webhook/notificação ao salvar template (log no audit).

## Considerações Técnicas
- Necessário expor `workflow.templates` via CORS (já liberado através do FastAPI + CORSMiddleware).
- Autenticação: reutilizar tokens JWT existentes (chamar API com `Authorization: Bearer ...`).
- Deploy: servir o frontend separado (Vercel/Netlify) ou via proxy (FastAPI + StaticFiles com build).

## Próximos Passos
1. Criar projeto React no diretório `frontend/` com boilerplate e rota `/templates`.
2. Desenvolver lista + formulário simples (sem drag & drop) lendo/gravando via API existente.
3. Iterar adicionando drag & drop, validações visuais e pré-visualizações.
