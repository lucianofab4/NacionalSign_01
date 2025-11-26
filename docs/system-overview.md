# NacionalSign Technical Blueprint

## 1. Vision & Goals
- Deliver a Brazilian SaaS platform for digital and electronic signatures with superior UX vs DocuSign/ClickSign.
- Guarantee legal validity through MP 2.200-2/2001 compliance, ICP-Brasil integration, and auditable trails.
- Support multi-company, multi-area workloads with granular access segregation and reusable signing flows.

## 2. Signature Modalities
| Type | Description | Legal Standing |
|------|-------------|----------------|
| Digital (ICP-Brasil) | Certificate-based signatures via Certisign/Soluti/SafeSign APIs (A1/A3). | Full legal equivalence to handwritten signature. |
| Electronic (Login + Password) | Authenticated session with CPF, password, IP/device enforcement. | Strong evidential value (authorship proven). |
| Electronic Simple (Token) | Confirmation through one-time token (email/SMS/app) or explicit consent button. | Valid with audit logs and consent trails. |

## 3. Compliance Checklist
- SHA256 hashing for every stored and generated document.
- Official timestamp service (ICP-Brasil TSA).
- Immutable audit logs capturing IP, user agent, geolocation, CPF, action, datetime.
- Public authenticity page exposing hash, signers, timestamp, and status.
- LGPD: minimal data collection, consent records, right-to-forget workflows, data encryption at rest (AES-256) and transit (TLS 1.2+).

## 4. User Model & Permissions
- Tenants (companies) own multiple areas (departments).
- Mandatory area membership for all users; documents isolated per area.
- Roles:
  - Tenant Admin: manages users, areas, billing.
  - Area Manager: defines flows, templates, monitors execution.
  - User: uploads, signs, interacts with area documents.
  - Procurator: delegated signer acting on behalf of another account.
- Access control enforced via RBAC + tenant/area scoping in queries.

## 5. Core Modules & Responsibilities
1. **Identity & Access**: JWT auth, session management, 2FA, procurator delegation workflows.
2. **Document Engine**: File intake, virus scan, format conversion (LibreOffice headless / PDFBox), hashing, secure storage.
3. **Workflow Designer**: Visual builder, sequential/parallel routing, deadlines, escalation logic, reusable templates.
4. **Signature Orchestration**: Handles signature requests, ICP integration, token/credential validation, refusal/delegation handling.
5. **Audit & Compliance**: Timestamping, log sealing, reporting, verification portal.
6. **Notifications**: Email/SMS push, reminders, status updates, failure alerts.
7. **Billing & SaaS Ops**: Plan limits, payment gateway integration, usage metering.

## 6. High-Level Architecture
- **API Layer**: FastAPI app exposing REST endpoints, documented via OpenAPI. Serves SPA frontend and third-party integrations.
- **Worker Layer**: Celery or RQ workers for asynchronous tasks (document conversion, notifications, timestamping).
- **Database**: PostgreSQL with logical replication to analytics/reporting store (future).
- **Cache/Queue**: Redis for background jobs, rate limiting, token storage.
- **Storage**: Object store (AWS S3 / MinIO) with server-side encryption and lifecycle policies.
- **Integrations**:
  - ICP-Brasil certification providers (via REST/SOAP connectors).
  - Email/SMS providers (SendGrid, TotalVoice, Twilio).
  - Payment gateways (Mercado Pago, Stripe, PagSeguro).
  - Geolocation/IP reputation services (optional).

## 7. Data Model Snapshot
- `tenants`, `areas`, `users`, `user_area_roles`, `procurations`.
- `documents`, `document_versions`, `document_parties`, `document_artifacts` (hashes, timestamps, signed PDFs).
- `workflows`, `workflow_steps`, `workflow_templates`, `workflow_assignments`.
- `signature_requests`, `signatures`, `refusals`, `delegations`.
- `audit_logs`, `auth_logs`, `billing_plans`, `subscriptions`, `payments`.

## 8. Operational Flow
1. Authenticated user (optionally 2FA) initiates document upload or uses template.
2. Document normalized to PDF, hash calculated, stored securely.
3. User defines parties, roles, signature order (sequential/parallel), deadlines, 2FA rules.
4. System issues signature requests and notifications per configured channels.
5. Signers access portal, validate identity (ICP, login, or token) and sign or refuse with justification.
6. Each action logged immutably, timestamped, and optionally countersigned by TSA.
7. Upon completion, final PDF bundle (document + audit report) generated and distributed.
8. Document retains public verification route exposing status, hash, and signers.

## 9. Security Considerations
- Secret rotation via Vault/KMS; secrets never stored in repo.
- Row-level filtering per tenant/area; guard rails at ORM and DB level.
- WORM (write once read many) policy for audit logs; append-only tables with checksums.
- Daily incremental backups, 7-day retention minimum, tested restores.
- Continuous monitoring: login anomalies, signature attempt rates, suspicious IPs.

## 10. Delivery Phases
1. Foundation: authentication, tenants, areas, basic document CRUD.
2. Workflow engine: visual builder, template persistence, sequential execution.
3. Signature integrations: ICP providers, OTP service, procuration flows.
4. Audit and compliance: timestamping, hash verification, public portal.
5. Monetization: plan enforcement, payment integration, invoicing.
6. Hardening & launch: penetration testing, observability stack, auto-scaling policies.

## 11. Open Questions
- Final stack for document conversion (LibreOffice vs cloud service).
- Preferred ICP provider and integration protocol.
- SMS provider availability and SLA.
- Localization requirements beyond Portuguese.
- Target deployment cloud (AWS, Azure, GCP) to finalize infra scripts.
