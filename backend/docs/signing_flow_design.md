# Assinatura Local com Certificado do Signatário

Este documento descreve as alterações previstas no backend para suportar a assinatura de documentos usando o certificado (A1/A3) do próprio signatário por meio do agente desktop.

## Visão Geral do Fluxo

1. O front-end solicita ao backend um **pedido de assinatura** para um workflow/documento específico.
2. O backend gera os dados necessários (hash do PDF, informações de auditoria) e grava uma `SignatureSession`.
3. O front repassa esses dados ao agente local. O agente apresenta os certificados disponíveis, coleta PIN se necessário e gera a assinatura PKCS#7.
4. A assinatura resultante volta ao front-end, que a envia ao backend para **conclusão da assinatura**.
5. O backend valida a assinatura, persiste os artefatos e atualiza o estado do workflow/documento.

## Novos Endpoints

### 1. Criar sessão de assinatura
`POST /api/v1/workflows/{workflow_id}/signing/request`

**Objetivo**
- Validar permissões do usuário atual.
- Garantir que o workflow esteja em etapa aguardando a ação do usuário.
- Gerar hash/cms input e retornar metadados para o agente.

**Resposta**
```json
{
  "session_id": "uuid",
  "document_id": "uuid",
  "workflow_step_id": "uuid",
  "hash_algorithm": "SHA256",
  "content_to_sign": "<base64>",
  "display_name": "Contrato X",
  "reason": "Assinatura do documento",
  "location": "NacionalSign",
  "expires_at": "2025-10-16T22:34:00Z"
}
```

### 2. Completar sessão de assinatura
`POST /api/v1/workflows/{workflow_id}/signing/complete`

**Objetivo**
- Receber a assinatura PKCS#7 ou PDF assinado.
- Validar integridade, cadeia ICP, correspondência de CPF (quando disponível).
- Persistir artefatos (assinatura, cadeia, timestamp).
- Avançar o workflow/documento.

**Payload típico**
```json
{
  "session_id": "uuid",
  "signature": "<base64-pkcs7>",
  "certificate_subject": "...",
  "certificate_serial": "...",
  "certificate_issuer": "...",
  "certificate_crl_urls": ["..."],
  "signing_time": "2025-10-16T22:36:12Z"
}
```

## Persistência

### Nova Tabela: `signature_sessions`
Campos sugeridos:
- `id` (UUID) – chave primária.
- `workflow_id`, `workflow_step_id`, `document_id`, `tenant_id`.
- `requested_by_id` – usuário que iniciou.
- `party_id` – signatário responsável.
- `hash_algorithm`, `content_hash`, `content_bytes` (quando armazenado).
- `status` – `pending`, `completed`, `expired`.
- `expires_at`, `completed_at`.
- Metadados de auditoria (IP, user-agent).

### Artefatos
- Reaproveitar `AuditArtifact` para armazenar `signature_p7s`, `signature_pdf` e `signature_certificate`.
- Registrar eventos em `AuditLog` (ex.: `signature_completed`, `signature_failed`).

## Validações Necessárias

1. **Estado do workflow**  
   - Etapa atual deve pertencer ao signatário autenticado.
   - Workflow não pode estar cancelado/completo.

2. **Assinatura**  
   - Verificar `SignedCms` ou equivalente:
     - O hash do conteúdo assinado corresponde ao documento atual.
     - Certificado possui chave privada válida, dentro da validade, não revogado (CRL/OCSP se disponível).
     - Opcional: verificar se CPF/subject corresponde ao signatário cadastrado.
   - Registrar falhas (ex.: cadeia inválida, certificado expirado).

3. **Segurança**  
   - `session_id` expira rapidamente (ex.: 10 minutos).
   - Tokens anti-replay (cada sessão pode ser usada uma única vez).
   - IP/User-Agent do pedido final deve casar com o inicial (quando possível).

## Integração com Workflows

1. Após validação da assinatura:
   - Marcar `SignatureSession` como `completed`.
   - Atualizar o `WorkflowStep` para `completed`.
   - Se todas as etapas estiverem concluídas, finalizar o workflow/documento (`DocumentStatus.COMPLETED`).

2. **Relatório final**  
   - Ao gerar relatório, anexar:
     - PDF original.
     - Assinatura PKCS#7 ou PDF assinado.
     - Informações do certificado e timestamp.

## Próximos Passos
- Definir esquema SQL (migration alembic) para `signature_sessions`.
- Implementar serviço `SignatureService` com:
  - `create_session` – validações + geração de hash.
  - `complete_session` – validação PKCS#7 + avanço do workflow.
- Atualizar testes (`tests/test_services_workflow.py`) para cobrir estado `pending` → `signed`.

---
