# Signing Agent Prototype

Prottipo em C# /.NET 8 que expe um agente HTTP local e uma CLI para assinar arquivos usando certificados A1 e A3 no NacionalSign.

## Estrutura
- `SigningAgent.csproj`  aplicao console/servio (CLI + host HTTP).
- `Program.cs`  parsing de argumentos, prompts de PIN e ciclo de vida do host.
- `SigningAgentHost.cs`  servidor HTTP, seleo de certificados e eventos de PIN.
- `Services/CertificateService.cs`  consulta certificados da store do Windows.
- `Services/SigningService.cs`  assinatura CMS com suporte a PIN via `SetPinForPrivateKey` (quando disponvel).
- `Services/PdfSigningService.cs`  aplica marcao visual (protocolo) e embute a assinatura em PDFs via iText.
- `SigningAgent.UI`  interface WPF para selecionar o certificado padro e monitorar o agente.
- `SigningAgent.Tests`  testes xUnit com cenrios de PIN e endpoints HTTP.

## Build
```powershell
cd backend\signing-agent-prototype
dotnet restore
dotnet build SigningAgent.sln
```

## CLI
```powershell
# lista certificados disponveis
dotnet run --project SigningAgent.csproj -- list

# assina arquivo binrio (gera .p7s)
dotnet run --project SigningAgent.csproj -- sign --cert-index 0 --file C:\documentos\contrato.pdf

# aplica checklist/protocolo e assinatura em PDF
dotnet run --project SigningAgent.csproj -- pdf-sign --cert-index 0 --input contrato.pdf --output contrato-assinado.pdf --protocol NS-2025-0001 --action "Documento enviado;Assinado eletronicamente"

# inicia o agente HTTP
dotnet run --project SigningAgent.csproj -- serve --port 9250

# expõe o agente para outras interfaces (ex.: WSL/Docker)
dotnet run --project SigningAgent.csproj -- serve --port 9250 --bind 0.0.0.0
```

Endpoints do agente:
- `GET http://127.0.0.1:PORT/status`
- `GET http://127.0.0.1:PORT/certificates`
- `POST http://127.0.0.1:PORT/sign`
- `POST http://127.0.0.1:PORT/sign/pdf`

Payload de exemplo:
```json
{
  "certIndex": 0,
  "payload": "BASE64_DO_DOCUMENTO", // bytes originais em Base64
  "detached": true
}
```

Payload para `/sign/pdf`:
```json
{
  "certIndex": 0,
  "payload": "BASE64_DO_PDF",
  "protocol": "NS-2025-0001",
  "actions": ["Documento recebido", "Assinado eletronicamente"],
  "signatureType": "Assinatura digital ICP-Brasil",
  "authentication": "Certificado digital (PIN)"
}
```

## Interface WPF
```powershell
cd backend\signing-agent-prototype
& "C:\\Program Files\\dotnet\\dotnet.exe" run --project SigningAgent.UI/SigningAgent.UI.csproj
```

A janela lista certificados com chave privada, permite definir o padro e acompanha o status do agente. O PIN  solicitado em um dilogo modal sempre que necessrio. A seleo padro  persistida em `%AppData%\SigningAgent\default-certificate.json`.

## Testes automatizados
```powershell
dotnet test SigningAgent.Tests/SigningAgent.Tests.csproj
```

Os testes sobem o host em porta efmera, exercitam `/status`, `/sign`, cenrios de PIN correto/errado e ausncia de certificados.

## Requisitos para A3
- Middleware/driver do token instalado no Windows.
- Certificado disponvel via store pessoal (CurrentUser).
- PIN configurado; o agente solicitar o valor quando necessrio (UI/CLI/HTTP).

## Observaes sobre PDFs
- A rotina `pdf-sign` utiliza iText 7 (licena AGPL) para aplicar marca d'gua, protocolo de aes e assinatura visvel.
- O PDF final  salvo em modo append, preservando o contedo original e registrando a assinatura em `/ByteRange` com subfiltro `ETSI.CAdES.detached`.

## Prximos passos sugeridos
1. Implementar integrao PKCS#11 real em `Pkcs11Helper` para tokens que exigem middleware especfico.
2. Validar em ambiente de homologao com dispositivos A3 e cadeia ICP-Brasil completa.
3. Empacotar o agente (MSIX/MSI) e definir poltica de atualizao.
4. Conectar com o frontend do NacionalSign e registrar logs centralizados.

