# API Sketch

This document outlines the initial REST endpoints for the NacionalSign backend. The goal is to guide MVP development; full OpenAPI docs will be generated from FastAPI once the implementation matures.

## Auth & Identity
- `POST /auth/login` — credential login (email/CPF + password), returns JWT + refresh.
- `POST /auth/refresh` — refresh access token.
- `POST /auth/2fa/verify` — validate token for users with 2FA enabled.
- `POST /auth/procuration` — assume delegated identity (requires active procuration).

## Tenants & Areas
- `POST /tenants` — create company (admin only).
- `GET /tenants/{tenant_id}` — tenant profile and plan stats.
- `POST /tenants/{tenant_id}/areas` — create area.
- `GET /tenants/{tenant_id}/areas` — list areas with counts.

## Users & Roles
- `POST /areas/{area_id}/users` - invite user to area with role.
- `PATCH /users/{user_id}` - update profile, enable/disable 2FA.
- `POST /users/{user_id}/procurators` - assign procurator (delegate) with validity period.
- `GET /users/me` - current user profile, permissions.
- `POST /users/{user_id}/reset-password` - admin/owner generates a temporary password for manual delivery and audit logging.

## Documents
- `POST /areas/{area_id}/documents` — upload file, create document entry.
- `GET /documents/{document_id}` — fetch metadata and current status.
- `GET /areas/{area_id}/documents` — filter by status, participant, date.
- `POST /documents/{document_id}/versions` — upload new version before workflow starts.

## Workflows & Templates
- `POST /areas/{area_id}/workflows` — create workflow definition (sequential/parallel steps).
- `GET /areas/{area_id}/workflows` — list workflows (models and active instances).
- `POST /areas/{area_id}/workflow-templates` — save workflow as reusable template.
- `POST /workflow-templates/{template_id}/clone` — duplicate template with new name.

## Signature Requests
- `POST /documents/{document_id}/dispatch` — initiate signing process using workflow.
- `GET /signatures/{request_id}` — fetch signing request details for participant.
- `POST /signatures/{request_id}/actions` — sign, refuse (with reason), delegate, or request changes.
- `POST /signatures/{request_id}/token` — verify OTP token (email/SMS/app).

## Audit & Verification
- `GET /documents/{document_id}/audit` — download audit trail bundle (internal).
- `GET /verification/{code}` — public authenticity lookup.
- `GET /documents/{document_id}/hash` — retrieve stored hash and timestamp.

## Billing
- `GET /billing/plans` — available plans and limits.
- `POST /billing/subscriptions` — start or update subscription.
- `GET /billing/invoices` — list invoices by tenant.

## Webhooks & Integrations
- `POST /integrations/webhooks/{provider}` — ingest callback events (timestamp, payment, ICP updates).

## Notifications
- `POST /notifications/test` — send test notification to validate channels.

### Pagination & Filtering
- Apply standard pagination params: `page`, `page_size`.
- Common filters: `status`, `participant_cpf`, `date_from`, `date_to`, `area_id`.

### Error Handling
- Consistent problem detail responses: `{ "code": "string", "message": "string", "details": {} }`.
- Sensitive data (CPF, emails) masked when possible.

### Authentication
- `Authorization: Bearer <access_token>` for private endpoints.
- Public endpoints limited to verification and signing entry points.
