using CommandLine;
using SigningAgentPrototype.Models;
using SigningAgentPrototype.Services;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;

namespace SigningAgentPrototype;

internal static class Program
{
    public static void Main(string[] args)
    {
        Parser.Default.ParseArguments<ListOptions, SignOptions, ServeOptions, PdfSignOptions>(args)
            .WithParsed<ListOptions>(RunList)
            .WithParsed<SignOptions>(RunSign)
            .WithParsed<ServeOptions>(RunServe)
            .WithParsed<PdfSignOptions>(RunPdfSign)
            .WithNotParsed(_ => Environment.Exit(-1));
    }

    private static void RunList(ListOptions _)
    {
        var certService = new CertificateService();
        var certs = certService.GetCertificates(includeOnlyWithPrivateKey: true);

        if (certs.Count == 0)
        {
            Console.WriteLine("Nenhum certificado com chave privada encontrado.");
            return;
        }

        Console.WriteLine("Certificados disponiveis:");
        for (var i = 0; i < certs.Count; i++)
        {
            var cert = certs[i];
            Console.WriteLine($"{i}: {cert.Subject} | Serie: {cert.SerialNumber} | Emissor: {cert.Issuer}");
        }
    }

    private static void RunSign(SignOptions options)
    {
        var certService = new CertificateService();
        var certs = certService.GetCertificates(includeOnlyWithPrivateKey: true);

        if (options.CertIndex < 0 || options.CertIndex >= certs.Count)
        {
            Console.WriteLine("Indice de certificado invalido. Use o comando 'list' para ver as opcoes.");
            return;
        }

        if (!File.Exists(options.File))
        {
            Console.WriteLine("Arquivo nao encontrado para assinatura.");
            return;
        }

        var certificate = certs[options.CertIndex];
        var signingService = new SigningService();

        try
        {
            var outputPath = signingService.SignFileWithCertificate(options.File, certificate);
            Console.WriteLine($"Assinatura gerada com sucesso: {outputPath}");
            return;
        }
        catch (PinRequiredException)
        {
            // tentaremos coletar o PIN abaixo
        }
        catch (PinConfigurationException ex)
        {
            Console.WriteLine($"Nao foi possivel preparar o dispositivo para digitar o PIN: {ex.Message}");
            return;
        }

        for (var attempt = 1; attempt <= 3; attempt++)
        {
            var pin = PromptForPin(attempt);
            if (string.IsNullOrWhiteSpace(pin))
            {
                Console.WriteLine("Operacao cancelada  PIN nao informado.");
                return;
            }

            try
            {
                var outputPath = signingService.SignFileWithCertificate(options.File, certificate, pin);
                Console.WriteLine($"Assinatura gerada com sucesso: {outputPath}");
                return;
            }
            catch (PinValidationException)
            {
                Console.WriteLine("PIN invalido. Tente novamente.");
            }
            catch (PinConfigurationException ex)
            {
                Console.WriteLine($"Falha ao aplicar o PIN: {ex.Message}");
                return;
            }
        }

        Console.WriteLine("Limite de tentativas de PIN atingido.");
    }

    private static void RunServe(ServeOptions options)
    {
        using var host = new SigningAgentHost(options.Port, options.BindAddress);

        host.Started += (_, _) =>
        {
            var advertisedHost = string.IsNullOrWhiteSpace(options.BindAddress)
                ? "127.0.0.1"
                : options.BindAddress;
            Console.WriteLine($"Agente de assinatura ouvindo em http://{advertisedHost}:{options.Port}");
            if (advertisedHost == "0.0.0.0")
            {
                Console.WriteLine("Dica: use o IP desta maquina (ex.: http://192.168.x.x:{0}) para configurar o backend.", options.Port);
            }
        };
        host.Stopped += (_, _) => Console.WriteLine("Agente encerrado.");
        host.PinRequested += async context => await Task.Run(() => PromptForPinInteractive(context.Subject));

        host.Start();

        Console.WriteLine("Pressione Ctrl+C para encerrar.");

        var shutdown = new ManualResetEventSlim(false);
        Console.CancelKeyPress += (_, args) =>
        {
            args.Cancel = true;
            shutdown.Set();
        };

        shutdown.Wait();
        host.StopAsync().GetAwaiter().GetResult();
    }

    private static void RunPdfSign(PdfSignOptions options)
    {
        if (!File.Exists(options.Input))
        {
            Console.WriteLine($"Arquivo nao encontrado: {options.Input}");
            return;
        }

        var certService = new CertificateService();
        var certs = certService.GetCertificates(includeOnlyWithPrivateKey: true);

        if (options.CertIndex < 0 || options.CertIndex >= certs.Count)
        {
            Console.WriteLine("Indice de certificado invalido. Use o comando 'list' para ver as opcoes.");
            return;
        }

        var outputDirectory = Path.GetDirectoryName(Path.GetFullPath(options.Output));
        if (!string.IsNullOrWhiteSpace(outputDirectory))
        {
            Directory.CreateDirectory(outputDirectory);
        }

        var certificate = certs[options.CertIndex];
        var signingService = new SigningService();
        var pdfSigningService = new PdfSigningService(signingService);
        var pdfOptions = BuildPdfStampOptions(options, certificate);

        try
        {
            pdfSigningService.SignPdf(options.Input, options.Output, certificate, pdfOptions);
            Console.WriteLine($"PDF assinado gerado em: {options.Output}");
            return;
        }
        catch (PinRequiredException)
        {
            // tentaremos coletar o PIN abaixo
        }
        catch (PinConfigurationException ex)
        {
            Console.WriteLine($"Nao foi possivel preparar o dispositivo para digitar o PIN: {ex.Message}");
            return;
        }

        for (var attempt = 1; attempt <= 3; attempt++)
        {
            var pin = PromptForPin(attempt);
            if (string.IsNullOrWhiteSpace(pin))
            {
                Console.WriteLine("Operacao cancelada  PIN nao informado.");
                return;
            }

            try
            {
                pdfSigningService.SignPdf(options.Input, options.Output, certificate, pdfOptions, pin);
                Console.WriteLine($"PDF assinado gerado em: {options.Output}");
                return;
            }
            catch (PinValidationException)
            {
                Console.WriteLine("PIN invalido. Tente novamente.");
            }
            catch (PinConfigurationException ex)
            {
                Console.WriteLine($"Falha ao aplicar o PIN: {ex.Message}");
                return;
            }
        }

        Console.WriteLine("Limite de tentativas de PIN atingido.");
    }

    private static PdfStampOptions BuildPdfStampOptions(PdfSignOptions options, X509Certificate2 certificate)
    {
        var stampOptions = new PdfStampOptions
        {
            WatermarkText = string.IsNullOrWhiteSpace(options.Watermark)
                ? "Documento assinado eletronicamente"
                : options.Watermark,
            ProtocolNumber = string.IsNullOrWhiteSpace(options.Protocol)
                ? $"NS-{DateTime.UtcNow:yyyyMMddHHmmss}"
                : options.Protocol,
            FooterNote = string.IsNullOrWhiteSpace(options.FooterNote)
                ? "Documento valido somente com assinatura digital."
                : options.FooterNote,
            Reason = "Assinatura digital do NacionalSign",
            Location = "Brasil",
            SignerName = string.IsNullOrWhiteSpace(options.SignerName)
                ? certificate.GetNameInfo(X509NameType.SimpleName, false)
                : options.SignerName,
            SignaturePage = options.SignaturePage < 1 ? 1 : options.SignaturePage,
            SignatureRectWidth = options.SignatureWidth,
            SignatureRectHeight = options.SignatureHeight,
            SignatureRectMarginX = options.SignatureMarginX,
            SignatureRectMarginY = options.SignatureMarginY,
            SignatureFieldName = "NacionalSignSignature",
            SignatureType = string.IsNullOrWhiteSpace(options.SignatureType)
                ? "Assinatura digital ICP-Brasil"
                : options.SignatureType,
            AuthenticationMethod = string.IsNullOrWhiteSpace(options.Authentication)
                ? "Certificado digital (PIN)"
                : options.Authentication,
            CertificateDescription = string.IsNullOrWhiteSpace(options.CertificateDescription)
                ? certificate.GetNameInfo(X509NameType.SimpleName, false)
                : options.CertificateDescription,
            TokenDescription = string.IsNullOrWhiteSpace(options.TokenInfo)
                ? certificate.Issuer
                : options.TokenInfo,
            SignedAt = DateTimeOffset.Now
        };

        foreach (var action in options.Actions ?? Enumerable.Empty<string>())
        {
            if (!string.IsNullOrWhiteSpace(action))
            {
                stampOptions.Actions.Add(action.Trim());
            }
        }

        if (stampOptions.Actions.Count == 0)
        {
            stampOptions.Actions.Add("Documento enviado pelo NacionalSign.");
            stampOptions.Actions.Add("Assinatura digital aplicada com validade juridica.");
        }

        return stampOptions;
    }

    private static string? PromptForPin(int attempt)
    {
        Console.Write($"Digite o PIN (tentativa {attempt}/3, Enter para cancelar): ");
        return ReadHiddenInput();
    }

    private static string? PromptForPinInteractive(string subject)
    {
        Console.WriteLine();
        Console.WriteLine($"PIN solicitado para o certificado: {subject}");
        Console.Write("Informe o PIN (Enter para cancelar): ");
        var pin = ReadHiddenInput();
        Console.WriteLine();
        return string.IsNullOrWhiteSpace(pin) ? null : pin;
    }

    private static string? ReadHiddenInput()
    {
        var builder = new StringBuilder();

        while (true)
        {
            var key = Console.ReadKey(intercept: true);
            if (key.Key == ConsoleKey.Enter)
            {
                Console.WriteLine();
                break;
            }

            if (key.Key == ConsoleKey.Backspace)
            {
                if (builder.Length > 0)
                {
                    builder.Length--;
                    Console.Write("\b \b");
                }

                continue;
            }

            builder.Append(key.KeyChar);
            Console.Write('*');
        }

        return builder.ToString();
    }

    [Verb("list", HelpText = "Lista certificados disponiveis.")]
    private class ListOptions { }

    [Verb("sign", HelpText = "Assina um arquivo com o certificado selecionado.")]
    private class SignOptions
    {
        [Option("cert-index", Required = true, HelpText = "Indice do certificado (use 'list' para ver).")]
        public int CertIndex { get; set; }

        [Option("file", Required = true, HelpText = "Arquivo a ser assinado.")]
        public string File { get; set; } = string.Empty;
    }

    [Verb("serve", HelpText = "Inicia o agente HTTP local.")]
    private class ServeOptions
    {
        [Option("port", Default = 9250, HelpText = "Porta para escutar (padrao 9250).")]
        public int Port { get; set; }

        [Option("bind", Default = "127.0.0.1", HelpText = "Endereco para escutar (use 0.0.0.0 para permitir acesso externo/WSL).")]
        public string BindAddress { get; set; } = "127.0.0.1";
    }

    [Verb("pdf-sign", HelpText = "Aplica marcacoes visuais e assinatura digital a um PDF.")]
    private class PdfSignOptions
    {
        [Option("input", Required = true, HelpText = "Caminho do PDF original.")]
        public string Input { get; set; } = string.Empty;

        [Option("output", Required = true, HelpText = "Caminho do PDF assinado.")]
        public string Output { get; set; } = string.Empty;

        [Option("cert-index", Required = true, HelpText = "Indice do certificado (use 'list' para ver).")]
        public int CertIndex { get; set; }

        [Option("signer-name", HelpText = "Nome exibido no protocolo (padrao: nome do certificado).")]
        public string? SignerName { get; set; }

        [Option("protocol", HelpText = "Numero do protocolo exibido no rodape.")]
        public string? Protocol { get; set; }

        [Option("watermark", HelpText = "Texto do cabecalho em todas as paginas.")]
        public string? Watermark { get; set; }

        [Option("footer-note", HelpText = "Mensagem adicional no rodape.")]
        public string? FooterNote { get; set; }

        [Option("action", HelpText = "Itens do protocolo de acoes (separe com ';').", Separator = ';')]
        public IEnumerable<string>? Actions { get; set; }

        [Option("signature-type", HelpText = "Descricao do tipo de assinatura (ex.: Assinatura digital ICP-Brasil).")]
        public string? SignatureType { get; set; }

        [Option("authentication", HelpText = "Como o usuario autenticou (ex.: Certificado digital + PIN).")]
        public string? Authentication { get; set; }

        [Option("certificate-description", HelpText = "Descricao exibida do certificado digital.")]
        public string? CertificateDescription { get; set; }

        [Option("token-info", HelpText = "Informacoes sobre o token/dispositivo utilizado.")]
        public string? TokenInfo { get; set; }

        [Option("signature-page", Default = 1, HelpText = "Pagina onde o quadro de assinatura sera inserido.")]
        public int SignaturePage { get; set; }

        [Option("signature-width", Default = 250f, HelpText = "Largura do quadro de assinatura (pontos).")]
        public float SignatureWidth { get; set; } = 250f;

        [Option("signature-height", Default = 120f, HelpText = "Altura do quadro de assinatura (pontos).")]
        public float SignatureHeight { get; set; } = 120f;

        [Option("signature-margin-x", Default = 36f, HelpText = "Margem horizontal do quadro (pontos).")]
        public float SignatureMarginX { get; set; } = 36f;

        [Option("signature-margin-y", Default = 36f, HelpText = "Margem vertical do quadro (pontos).")]
        public float SignatureMarginY { get; set; } = 36f;
    }
}

