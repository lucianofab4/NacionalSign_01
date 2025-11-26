# Integração Frontend – Assinatura com Agente Local

Este plano descreve as mudanças necessárias no frontend (React/Vite) para suportar o agente desktop de assinatura com certificado do signatário.

## Componentes Principais

1. **Detecção do agente**  
   - Endpoint local padrão: `http://127.0.0.1:9250/status`.  
   - O frontend realiza um `fetch` com timeout curto; se responder `{"status":"ok","version":"1.0.0"}`, consideramos o agente disponível.
   - Caso contrário, exibe modal/tutorial solicitando a instalação.

2. **Modal de instalação**  
   - Conteúdo:
     - Passo a passo (download → executar → reiniciar navegador).
     - Link para o instalador (`https://app.seudominio.com/downloads/NacionalSignSignerSetup.msi`).
     - Botão “Já instalei” que força nova detecção.
   - Esse modal só aparece quando a detecção falha; podemos registrar em `localStorage` para não incomodar desnecessariamente.

3. **Fluxo de assinatura**  
   1. Usuário clica em “Assinar” na tela do workflow.
   2. Front chama `POST /api/v1/workflows/{id}/signing/request` e recebe `session_id`, `content_to_sign`, `display_name`, etc.
   3. Front chama o agente local:  
      ```ts
      await fetch('http://127.0.0.1:9250/sign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id,
          payload: content_to_sign,
          hash_algorithm,
        }),
      });
      ```
   4. O agente abre janela de seleção (certificado, PIN).  
      Retorna `signature`, `certificate_subject`, `serial`, etc.
   5. Front envia os dados para `POST /api/v1/workflows/{id}/signing/complete`.
   6. Exibe toast de sucesso ou mensagem de erro.

4. **Tratamento de erros**  
   - `fetch` para o agente falhou → exibir modal de instalação.  
   - Agente retornou erro (ex.: certificado inválido, PIN incorreto) → mostrar mensagem com detalhes.  
   - Backend rejeitou a assinatura → exibir mensagem e registrar no log.

## Hooks e Componentes a Criar

1. `useSigningAgent` (hook):
   - `isAgentAvailable`: estado boolean + função `checkAgent()`.
   - `sign(payload)` → abstrai chamada ao agente local.

2. `SignDocumentDialog`:
   - Recebe `workflowId`, `stepId`.
   - Gerencia requisição ao backend, progress bar, logs.

3. `InstallAgentModal`:
   - Mensagens, link de download, botão “testar novamente”.
   - Opcional: link para documentação e contato de suporte.

4. Atualização das páginas:
   - `WorkflowDetailsPage`: integrar o botão “Assinar” ao novo fluxo.
   - `Dashboard`/`Home`: indicar status (documentos pendentes de assinatura com agente).

## Estados e Armazenamento

1. `localStorage`:
   - `nacionalsign.signAgentDismissed` → evita mostrar o modal repetidamente.
   - `nacionalsign.signAgentVersion` → usado para invalidar cache quando lançarmos update.

2. Redux / Zustand (se usarmos store global):
   - Estado para `agentStatus: 'unknown' | 'available' | 'unavailable' | 'checking'`.

## Experiência do Usuário

1. **Primeira assinatura**:
   - Modal com instruções (detecção falhou).
   - Link de download + tutorial (video/gif).
   - Após instalação, botão “Testar novamente”.

2. **Assinatura bem-sucedida**:
   - Mostrar certificado utilizado (subject + issuer).
   - Atualizar timeline do workflow imediatamente.
   - Oferecer download do recibo/relatório.

3. **Fallback**:
   - Se o usuário não instalar o agente, permitir exportar o arquivo e orientar a assinatura manual via ICP assina? (opcional).

## Segurança

1. `session_id` + token temporário do backend deve ser enviado ao agente. O agente exige esse token para impedir chamadas externas.
2. `fetch` para o agente deve usar `credentials: 'omit'`.
3. Registros de tentativa: enviar `userAgent`, `ip` (do backend) para auditoria.

## Testes

1. Ambiente sem agente:
   - Fluxo deve abrir modal de instalação.

2. Ambiente com agente (simulado):
   - Mockar respostas `status` e `sign`.
   - Fluxo deve prosseguir até `signing/complete`.

3. Error cases:
   - Agente retornando erro (`PIN_INCORRECT`, `CERT_NOT_FOUND`).
   - Backend rejeitando assinatura.

Com esses pontos implementados, o front passa a detectar automaticamente a presença do agente, orientar a instalação quando necessário e intermediar a assinatura junto ao backend. O “passo final” (instalar o agente real) fica por conta do usuário, mas a UX garante que ninguém ficará perdido no processo.
