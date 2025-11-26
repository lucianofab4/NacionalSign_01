# Data Model Outline

## Tenant & Access Control
- `tenants`: id (UUID), name, slug, cnpj, plan_id, status, created_at.
- `areas`: id, tenant_id, name, description, created_at.
- `users`: id, tenant_id, area_id (default), name, cpf, email, password_hash, profile, is_active, two_factor_enabled, created_at.
- `user_areas`: user_id, area_id, role, created_at.
- `procurations`: id, principal_user_id, delegate_user_id, valid_from, valid_until, status, created_at.

## Documents & Artifacts
- `documents`: id, tenant_id, area_id, name, status, current_version_id, created_by, created_at.
- `document_versions`: id, document_id, storage_path, original_filename, mime_type, size_bytes, sha256, created_at.
- `document_parties`: id, document_id, user_id (nullable for external), full_name, cpf, email, phone, role, order_index, two_factor_type, status.
- `document_artifacts`: id, document_id, type (hash, signed_pdf, audit_report), storage_path, sha256, created_at.

## Workflows & Execution
- `workflow_templates`: id, tenant_id, area_id, name, description, config (JSON), is_active, created_at.
- `workflows`: id, document_id, template_id (nullable), status, started_at, completed_at.
- `workflow_steps`: id, workflow_id, step_index, execution_type (sequential|parallel), role, required, deadline_at, config (JSON).

## Signatures & Events
- `signature_requests`: id, workflow_step_id, party_id, token_channel, token_sent_at, token_hash, expires_at, status.
- `signatures`: id, signature_request_id, type (icp|login|token), signed_at, signer_ip, signer_user_agent, location_lat, location_lon, digest_sha256, certificate_serial (if ICP).
- `refusals`: id, signature_request_id, reason, refused_by, refused_at.
- `delegations`: id, signature_request_id, from_party_id, to_party_id, delegated_at.
- `timestamps`: id, document_id, tsa_serial, issued_at, payload, signature.

## Audit & Security
- `audit_logs`: id, document_id, event_type, actor_id, actor_role, ip, user_agent, geo, metadata (JSON), created_at.
- `auth_logs`: id, user_id, event_type, ip, user_agent, device_id, success, created_at.
- `webhook_events`: id, provider, event_key, payload, processed_at, status.

## Billing
- `plans`: id, name, document_quota, user_quota, price_monthly, price_yearly.
- `subscriptions`: id, tenant_id, plan_id, status, valid_until, auto_renew, created_at.
- `invoices`: id, tenant_id, gateway, external_id, amount, due_date, status, paid_at.
- `usage_metrics`: id, tenant_id, period_start, period_end, documents_sent, signatures_collected.

## Support Tables
- `files`: id, owner_type, owner_id, storage_path, bucket, size_bytes, mime_type, sha256, created_at.
- `notifications`: id, target_contact, channel, message_template, context (JSON), status, sent_at.

> Primary keys use UUIDv7 for sortable entropy; timestamps stored in UTC.
