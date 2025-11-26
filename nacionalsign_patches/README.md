# Patch: Envio/assinatura e Tela de Documento Assinado

Este pacote traz ajustes e arquivos prontos para:
- Enviar documento para assinatura (já coberto pelo seu `api.ts`) e
- Implementar a **Tela de visualização de documento assinado** com botão **“Arquivo Assinado”** conforme os requisitos.

## O que está incluído

```
src/
  api.ts                       # Versão ajustada (inclui requires_certificate e endpoints de download pós-assinatura)
  components/
    PartiesSignatureMethodSelector.tsx  # Seletor de tipo de assinatura por participante (Eletrônica vs Digital A1/A3)
  pages/
    DocumentSignedView.tsx     # Tela exclusiva do documento assinado (cabeçalho, detalhes, envolvidos, download)
  utils/
    download.ts                # Helpers para baixar e zipar arquivos no front
```

> **Observação**: seu projeto já possui várias funções de API para criar documentos, subir versões, criar campos e partes, e despachar workflows. Este patch foca na **visualização pós-assinatura** + **download** e no **controle de tipo de assinatura por participante**.

## Novidades no `api.ts`

1. Campos adicionais em `DocumentParty` e `DocumentPartyPayload`:
   - `requires_certificate?: boolean | null` — força que o participante assine **somente** com certificado digital A1/A3.
   - `signed_at?: string | null` — opcional para exibir quando a assinatura ocorreu.

   > **Efeito na UI**: quando `requires_certificate=true`, desabilitamos nome digitado/desenho/imagem.

2. **Novos endpoints sugeridos** para downloads pós-assinatura (ajuste as URLs se seu backend usar outras rotas):
   - `GET /api/v1/documents/:id/signed-artifacts` → retorna `{ pdf_url, p7s_urls[], has_digital_signature }`.
   - `GET /api/v1/documents/:id/downloads/signed-package` → retorna **ZIP** (`responseType: 'blob'`).

   **Funções novas:**
   - `fetchSignedArtifacts(documentId)`
   - `downloadSignedPackage(documentId)`
   - `fetchDocument(documentId)` para carregar detalhes do documento individual

3. Mantidas todas as funções existentes do seu `api.ts` original.

## Como instalar

1. **Copie** os arquivos deste pacote para seu projeto (substitua `src/api.ts` pela versão deste patch e adicione os novos componentes/páginas).
2. Instale as dependências de download/zip no front:
   ```bash
   npm i file-saver jszip
   # ou
   yarn add file-saver jszip
   ```
3. Garanta que as rotas incluam a nova página. Exemplo (React Router):
   ```tsx
   // src/App.tsx (ou onde você registra as rotas)
   import { BrowserRouter, Routes, Route } from 'react-router-dom';
   import DocumentSignedView from './pages/DocumentSignedView';

   export default function App() {
     return (
       <BrowserRouter>
         <Routes>
           {/* ...outras rotas... */}
           <Route path="/documents/:id/signed" element={<DocumentSignedView />} />
         </Routes>
       </BrowserRouter>
     );
   }
   ```

4. **Navegação**: após a lista de documentos, ao clicar em um documento com status `signed`, redirecione para `/documents/:id/signed`.

## Botão “Arquivo Assinado” / “Baixar PDF”

- Primeiro tenta baixar o **ZIP pronto** do backend (`/downloads/signed-package`).  
- Se o endpoint não existir, faz **fallback**:
  - Chama `/signed-artifacts` para obter `pdf_url` e a lista de `p7s_urls`.
  - **Se não houver assinatura digital**, baixa **apenas o PDF** com marca d’água + protocolo.
  - **Se houver assinatura digital**, baixa o PDF e **todas as .p7s** e gera um **ZIP client-side** (JSZip).

## Seletor de Tipo de Assinatura por Participante

O componente `PartiesSignatureMethodSelector` exibe duas opções por participante:
- **Eletrônica** → seta `requires_certificate=false` e libera nome digitado/imagem/desenho.
- **Digital (A1/A3)** → seta `requires_certificate=true` e **desabilita** nome digitado/imagem/desenho.

> A função `updateDocumentParty` é chamada, então o backend precisa aceitar o campo `requires_certificate`. Caso seu backend use outro nome ou endpoint, ajuste no `api.ts`.

## Observações de Backend

Para cumprir 100% do requisito:
- **Geração do PDF** com **marca d’água** e **protocolo de ações** deve ser feita no backend ao concluir a assinatura.
- Para assinaturas **digitais A1/A3**, o backend deve disponibilizar os **arquivos `.p7s`** (um por signatário digital) e/ou gerar o **ZIP** já pronto.
- Preveja o campo `requires_certificate` (ou equivalente) na entidade de participante.

Se você me enviar os nomes reais dos endpoints (ou o OpenAPI/Swagger), eu ajusto o `api.ts` exatamente conforme seu backend.

## Requisitos cobertos

- ✅ Documento continua na lista e abre uma **tela exclusiva** de visualização.
- ✅ **Cabeçalho e Ações** com botão “Arquivo Assinado” (download conforme regras).
- ✅ **Detalhes do Documento** (nome, datas, status, origem, empresa*).
- ✅ **Informações de Assinaturas** (participantes, papel, empresa, tipo de assinatura, data/hora).
- ✅ **Tipo de assinatura por participante** (eletrônica vs digital A1/A3) com travas de UI coerentes.
- ✅ **Download** em PDF ou ZIP com `.p7s` quando houver assinatura digital.

\* Campo “Empresa vinculada” será exibido quando o backend enviar essa informação no `DocumentRecord` (pode ser `tenant_id` + `tenant_name`, por exemplo).

---

### Dúvidas comuns

- **Falta algum arquivo?**  
  Se seu projeto tiver estrutura diferente (ex.: páginas dentro de `views/` ou rotas centralizadas em outro arquivo), me diga os caminhos e eu ajusto os imports/exports pra bater 100% com o seu repo.

- **Posso manter o meu `api.ts` e só aplicar o diff?**  
  Pode. Os blocos “NOVO” estão comentados no arquivo para facilitar o merge.

- **Quer que eu abra um PR em cima do seu repositório (GitHub/Drive)?**  
  Posso gerar o patch/PR se você conectar o repositório.

