# Auditoria e LGPD - NacionalSign

## Requisitos LGPD
- Consentimento explícito para coleta e tratamento de dados pessoais.
- Registro de logs de acesso, assinatura, e manipulação de documentos.
- Relatório de auditoria exportável por workflow/documento.
- Dados sensíveis criptografados em repouso e em trânsito.
- Opção de anonimização/exclusão sob demanda.
- Controle de acesso granular por área/usuário.

## Relatório de Auditoria (Exemplo)

- ID do workflow/documento
- Data/hora de criação
- Usuários envolvidos (nome, e-mail, área, perfil)
- Ações realizadas (upload, assinatura, aprovação, rejeição)
- IP/dispositivo de cada ação
- Carimbo de tempo ICP-Brasil
- Hash do documento
- Status final
- Observações/erros

## Exportação
- Relatórios podem ser gerados em PDF ou CSV via endpoint `/api/v1/audit/report/{workflow_id}`
- Inclui todos os eventos, metadados e logs do ciclo de vida do documento.

## Recomendações
- Validar consentimento e base legal antes de cada operação sensível.
- Auditar periodicamente os acessos e exportar relatórios para compliance.
- Documentar políticas de privacidade e termos de uso.
