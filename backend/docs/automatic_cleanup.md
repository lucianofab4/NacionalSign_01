# Sistema de Limpeza Automática de Documentos

## Visão Geral

O sistema de limpeza automática permite a exclusão definitiva de documentos que estão na lixeira há mais de 30 dias (ou período configurável).

## Componentes

### 1. Funções no DocumentService

- `hard_delete_document(document_id)`: Exclui permanentemente um documento específico
- `cleanup_deleted_documents(days=30)`: Limpa documentos na lixeira há mais de X dias

### 2. Script Standalone

**Arquivo**: `cleanup_deleted_documents.py`

**Uso**:
```bash
# Executar limpeza (30 dias por padrão)
python cleanup_deleted_documents.py

# Modo dry-run (apenas mostrar o que seria excluído)
python cleanup_deleted_documents.py --dry-run

# Configurar período personalizado
python cleanup_deleted_documents.py --days 60

# Executar com logs detalhados
python cleanup_deleted_documents.py --verbose

# Combinar opções
python cleanup_deleted_documents.py --days 7 --dry-run --verbose
```

### 3. API Endpoint

**Endpoint**: `POST /admin/cleanup-deleted-documents`

**Parâmetros**:
- `days` (int, padrão: 30): Número de dias para considerar documentos expirados
- `dry_run` (bool, padrão: false): Apenas contar documentos, não excluir

**Exemplo**:
```bash
# Dry-run via API
curl -X POST "http://localhost:8000/admin/cleanup-deleted-documents?days=30&dry_run=true" \
     -H "Authorization: Bearer YOUR_TOKEN"

# Execução real via API
curl -X POST "http://localhost:8000/admin/cleanup-deleted-documents?days=30" \
     -H "Authorization: Bearer YOUR_TOKEN"
```

## Configuração de Execução Automática

### Windows (Task Scheduler)

1. Abra o Task Scheduler
2. Crie uma nova tarefa básica
3. Configure para executar diariamente
4. Ação: Iniciar um programa
5. Programa: `python`
6. Argumentos: `caminho\para\cleanup_deleted_documents.py`
7. Iniciar em: `caminho\para\backend`

### Linux/Mac (Cron)

```bash
# Editar crontab
crontab -e

# Adicionar linha para execução diária às 2:00 AM
0 2 * * * cd /caminho/para/backend && python cleanup_deleted_documents.py
```

### Docker/Kubernetes

Criar um CronJob ou usar um scheduler interno da aplicação.

## Segurança

- O endpoint admin requer autenticação
- Apenas usuários com perfil "owner" ou "admin" podem executar
- Sempre teste com `--dry-run` primeiro
- Os arquivos são excluídos permanentemente do sistema de arquivos

## Logs

O sistema registra todas as operações de limpeza, incluindo:
- Número de documentos processados
- IDs dos documentos excluídos
- Erros durante a exclusão de arquivos
- Tempo de execução

## Monitoramento

Recomendado:
- Configurar alertas para falhas na execução
- Monitorar espaço em disco liberado
- Acompanhar logs de erro
- Validar que o processo não está consumindo recursos excessivos