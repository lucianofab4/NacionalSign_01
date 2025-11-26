# Pacote para deploy no Render

Esta pasta funciona como um checklist do que precisa estar no repositório público (GitHub) para o Render conseguir fazer o build completo. Copie os diretórios e arquivos listados abaixo para o repositório remoto – você não precisa arrastar arquivos gigantes ou binários desnecessários.

## Diretórios obrigatórios

- `backend/` – API FastAPI + Alembic + scripts. Inclua requirements/poetry, migrations e templates.
- `frontend/` – aplicação React/Vite. Inclua `package.json`, `vite.config`, assets etc.
- `signing-agent-prototype/` – código do agente desktop (mesmo não sendo executado no Render, faz parte do projeto).
- `docs/` – documentação e instruções complementares.
- `nacionalsign_patches/` (ou quaisquer módulos auxiliares usados pelo backend).
- Qualquer outro diretório com código reutilizado (por exemplo `app/`, `scripts/`, `infra/` caso existam).

## Arquivos na raiz do repositório

- `.gitignore` (para evitar enviar `node_modules`, dumps etc.).
- `README.md` (ajuda quem vai revisar o projeto).
- `.env.example` ou instruções equivalentes com as variáveis necessárias.
- Scripts utilitários que você usa localmente (`start_nacionalsign.py`, `replace_protocol.py`, etc.).
- Arquivos de configuração de infraestrutura (`alembic.ini`, `render.yaml`, `Dockerfile`, `docker-compose.yml` se usar).
- Qualquer arquivo `.ps1` ou `.sh` necessário para automatizar build/deploy/testes.

## O que **não** subir

- `node_modules/`, `.pytest_cache/`, `_storage/`, `log/` e outras pastas geradas.
- Binários enormes (ZIPs, instaladores) – mantenha fora do Git ou publique em releases separadas.
- Dumps de banco (`.sql`, `.bak`), chaves privadas, `.env` com senhas reais.

## Próximos passos

1. Confirme que tudo acima está versionado no Git (use `git status`).
2. Faça `git add`, `git commit` e `git push` para o GitHub.
3. No Render, aponte o serviço para esse repositório/branch e configure as variáveis de ambiente mencionadas no `.env.example`.

> Dica: se quiser automatizar o processo, crie um `render.yaml` no repositório definindo os serviços (backend, frontend, Postgres). Render reconhece esse arquivo e permite reproduzir o deploy com um clique.

