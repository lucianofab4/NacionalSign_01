using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using SigningAgentPrototype.Models;
using SigningAgentPrototype.Services;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography.Pkcs;
using System.Security.Cryptography.X509Certificates;
using System.Net;
using System.Threading;
using System.Threading.Tasks;

namespace SigningAgentPrototype;

public class SigningAgentHost : IDisposable
{
    private readonly int _port;
    private readonly string _bindAddress;
    private readonly Action<IServiceCollection>? _configureServices;
    private readonly CancellationTokenSource _cts = new();
    private Task? _hostTask;
    private TaskCompletionSource<bool>? _startedTcs;

    public event Func<CertificateRequestContext, X509Certificate2?>? CertificateRequested;
    public event Func<PinRequestContext, Task<string?>>? PinRequested;
    public event EventHandler? Started;
    public event EventHandler? Stopped;

    public SigningAgentHost(int port = 9250, string bindAddress = "127.0.0.1", Action<IServiceCollection>? configureServices = null)
    {
        _port = port;
        _bindAddress = bindAddress;
        _configureServices = configureServices;
    }

    public bool IsRunning => _hostTask is { IsCompleted: false };

    public int Port => _port;

    public void Start()
    {
        if (IsRunning)
        {
            return;
        }

        _startedTcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);

        _hostTask = Task.Run(async () =>
        {
            WebApplication? app = null;
            var started = false;
            try
            {
                var builder = WebApplication.CreateBuilder();

                builder.Logging.ClearProviders();
                builder.Logging.AddConsole();
                builder.Services.AddSingleton<CertificateService>();
                builder.Services.AddSingleton<SigningService>();
                builder.Services.AddSingleton<PdfSigningService>();
                builder.Services.AddCors(options =>
                {
                    options.AddDefaultPolicy(policy =>
                        policy.AllowAnyOrigin()
                              .AllowAnyHeader()
                              .AllowAnyMethod());
                });
                _configureServices?.Invoke(builder.Services);

                builder.WebHost.ConfigureKestrel(serverOptions =>
                {
                    var listenAddress = _bindAddress.Equals("localhost", StringComparison.OrdinalIgnoreCase)
                        ? "127.0.0.1"
                        : _bindAddress;
                    if (!IPAddress.TryParse(listenAddress, out var ipAddress))
                    {
                        ipAddress = IPAddress.Loopback;
                    }

                    serverOptions.Listen(ipAddress, _port);
                });

                app = builder.Build();
                app.UseCors();
                MapEndpoints(app);

                await app.StartAsync(_cts.Token).ConfigureAwait(false);
                started = true;
                _startedTcs.TrySetResult(true);
                OnStarted();
                await app.WaitForShutdownAsync(_cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (_cts.IsCancellationRequested)
            {
                _startedTcs?.TrySetCanceled(_cts.Token);
            }
            catch (Exception ex)
            {
                _startedTcs?.TrySetException(ex);
                throw;
            }
            finally
            {
                if (app is not null)
                {
                    try
                    {
                        await app.StopAsync().ConfigureAwait(false);
                    }
                    catch
                    {
                        // ignore cleanup failures
                    }
                }

                if (started)
                {
                    OnStopped();
                }
            }
        }, _cts.Token);
    }

    public async Task WaitUntilStartedAsync(TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        if (_startedTcs is null)
        {
            throw new InvalidOperationException("Host has not been started.");
        }

        await _startedTcs.Task.WaitAsync(timeout, cancellationToken).ConfigureAwait(false);
    }

    public async Task StopAsync()
    {
        if (!IsRunning)
        {
            return;
        }

        _cts.Cancel();
        if (_hostTask is not null)
        {
            try
            {
                await _hostTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // ignore expected cancellation
            }
        }

        _startedTcs = null;
    }

    private void MapEndpoints(WebApplication app)
    {
        app.MapGet("/status", (CertificateService certService) =>
        {
            var version = typeof(SigningAgentHost).Assembly.GetName().Version?.ToString() ?? "1.0.0";
            return Results.Json(new
            {
                status = "ok",
                version,
                certificates = certService.GetCertificates(includeOnlyWithPrivateKey: true).Count
            });
        });

        app.MapGet("/certificates", (CertificateService certService) =>
        {
            var certs = certService
                .GetCertificates(includeOnlyWithPrivateKey: true)
                .Select((cert, index) => new
                {
                    index,
                    subject = cert.Subject,
                    issuer = cert.Issuer,
                    serialNumber = cert.SerialNumber,
                    thumbprint = cert.Thumbprint,
                    notAfter = cert.NotAfter
                });

            return Results.Json(certs);
        });

        app.MapPost("/sign", async (HttpRequest request, CertificateService certService, SigningService signingService) =>
        {
            SignRequest? payload;
            try
            {
                payload = await request.ReadFromJsonAsync<SignRequest>().ConfigureAwait(false);
            }
            catch
            {
                return Results.BadRequest(new { error = "Payload invlido." });
            }

            if (payload is null || string.IsNullOrWhiteSpace(payload.Payload))
            {
                return Results.BadRequest(new { error = "Payload ausente." });
            }

            var certificates = certService.GetCertificates(includeOnlyWithPrivateKey: true);
            if (certificates.Count == 0)
            {
                return Results.BadRequest(new { error = "Nenhum certificado disponvel." });
            }

            var certificate = await ResolveCertificateAsync(certificates, payload).ConfigureAwait(false);
            if (certificate is null)
            {
                return Results.BadRequest(new { error = "Certificado no selecionado." });
            }

            byte[] dataToSign;
            try
            {
                dataToSign = Convert.FromBase64String(payload.Payload);
            }
            catch
            {
                return Results.BadRequest(new { error = "Payload no est em Base64 vlido." });
            }

            try
            {
                var signedCms = await SignWithPinSupportAsync(signingService, certificate, dataToSign, payload.Detached).ConfigureAwait(false);
                var response = new SignResponse
                {
                    Signature = Convert.ToBase64String(signedCms.Encode()),
                    CertificateSubject = certificate.Subject,
                    CertificateSerial = certificate.SerialNumber,
                    CertificateIssuer = certificate.Issuer,
                    SignedAt = DateTime.UtcNow
                };

                return Results.Json(response);
            }
            catch (PinValidationException)
            {
                return Results.BadRequest(new { error = "PIN invlido ou recusado." });
            }
            catch (PinConfigurationException ex)
            {
                return Results.BadRequest(new { error = ex.Message });
            }
            catch (PinRequiredException)
            {
                return Results.BadRequest(new { error = "PIN obrigatrio no informado." });
            }
            catch (Exception ex)
            {
                return Results.BadRequest(new { error = $"Falha ao assinar: {ex.Message}" });
            }
        });

        app.MapPost("/sign/pdf", async (PdfSignRequest request, CertificateService certService, SigningService signingService, PdfSigningService pdfSigningService) =>
        {
            if (request is null || string.IsNullOrWhiteSpace(request.Payload))
            {
                return Results.BadRequest(new { error = "Payload ausente." });
            }

            byte[] pdfBytes;
            try
            {
                pdfBytes = Convert.FromBase64String(request.Payload);
            }
            catch
            {
                return Results.BadRequest(new { error = "Payload não está em Base64 válido." });
            }

            var certificates = certService.GetCertificates(includeOnlyWithPrivateKey: true);
            if (certificates.Count == 0)
            {
                return Results.BadRequest(new { error = "Nenhum certificado disponível." });
            }

            var certificate = await ResolveCertificateAsync(certificates, request.CertIndex, request.Thumbprint).ConfigureAwait(false);
            if (certificate is null)
            {
                return Results.BadRequest(new { error = "Certificado não selecionado." });
            }

            var options = BuildPdfStampOptions(request, certificate);

            var tempInput = Path.Combine(Path.GetTempPath(), $"ns-input-{Guid.NewGuid():N}.pdf");
            var tempOutput = Path.Combine(Path.GetTempPath(), $"ns-output-{Guid.NewGuid():N}.pdf");
            string? tempPkcs7Path = null;

            string? pkcs7Base64 = null;

            try
            {
                await File.WriteAllBytesAsync(tempInput, pdfBytes).ConfigureAwait(false);

                try
                {
                    await SignPdfWithPinSupportAsync(pdfSigningService, certificate, options, tempInput, tempOutput).ConfigureAwait(false);
                }
                catch (PinValidationException)
                {
                    return Results.BadRequest(new { error = "PIN inválido ou recusado." });
                }
                catch (PinConfigurationException ex)
                {
                    return Results.BadRequest(new { error = ex.Message });
                }
                catch (PinRequiredException)
                {
                    return Results.BadRequest(new { error = "PIN obrigatório não informado." });
                }

                // === Exportar PKCS#7 (.p7s) ===
                try
                {
                    Console.WriteLine("[DEBUG] Iniciando geração do PKCS#7 detached...");
                    var signedCms = await SignWithPinSupportAsync(signingService, certificate, pdfBytes, true).ConfigureAwait(false);
                    var encoded = signedCms.Encode();
                    tempPkcs7Path = Path.ChangeExtension(tempOutput, ".pdf.p7s");
                    await File.WriteAllBytesAsync(tempPkcs7Path, encoded).ConfigureAwait(false);
                    pkcs7Base64 = Convert.ToBase64String(encoded);
                    Console.WriteLine($"[PKCS7] Gerado com sucesso: {tempPkcs7Path}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[ERRO PKCS7] {ex.GetType().Name}: {ex.Message}");
                    Console.WriteLine($"StackTrace: {ex.StackTrace}");
                }

                var outputBytes = await File.ReadAllBytesAsync(tempOutput).ConfigureAwait(false);
                var response = new PdfSignResponse
                {
                    Pdf = Convert.ToBase64String(outputBytes),
                    Protocol = options.ProtocolNumber ?? string.Empty,
                    SignatureType = options.SignatureType,
                    Authentication = options.AuthenticationMethod,
                    P7s = pkcs7Base64
                };

                return Results.Json(response);
            }
            catch (Exception ex)
            {
                return Results.BadRequest(new { error = $"Falha ao assinar PDF: {ex.Message}" });
            }
            finally
            {
                try
                {
                    if (File.Exists(tempInput))
                        File.Delete(tempInput);
                }
                catch
                {
                }

                try
                {
                    if (File.Exists(tempOutput))
                        File.Delete(tempOutput);
                }
                catch
                {
                }

            }
        });
    }

    private async Task<SignedCms> SignWithPinSupportAsync(SigningService signingService, X509Certificate2 certificate, byte[] dataToSign, bool detached)
    {
        try
        {
            return signingService.SignBytes(dataToSign, certificate, detached);
        }
        catch (PinRequiredException)
        {
            var pin = await RequestPinAsync(certificate).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(pin))
            {
                throw;
            }

            return signingService.SignBytes(dataToSign, certificate, detached, pin);
        }
    }

    private async Task SignPdfWithPinSupportAsync(PdfSigningService pdfSigningService, X509Certificate2 certificate, PdfStampOptions options, string inputPath, string outputPath)
    {
        try
        {
            await Task.Run(() => pdfSigningService.SignPdf(inputPath, outputPath, certificate, options)).ConfigureAwait(false);
        }
        catch (PinRequiredException)
        {
            var pin = await RequestPinAsync(certificate).ConfigureAwait(false);
            if (string.IsNullOrWhiteSpace(pin))
            {
                throw;
            }

            await Task.Run(() => pdfSigningService.SignPdf(inputPath, outputPath, certificate, options, pin)).ConfigureAwait(false);
        }
    }

    private async Task<string?> RequestPinAsync(X509Certificate2 certificate)
    {
        if (PinRequested is null)
        {
            return null;
        }

        var context = new PinRequestContext(certificate.Subject, certificate.Issuer);
        foreach (Func<PinRequestContext, Task<string?>> handler in PinRequested.GetInvocationList())
        {
            var pin = await handler(context).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(pin))
            {
                return pin;
            }
        }

        return null;
    }

    private Task<X509Certificate2?> ResolveCertificateAsync(IReadOnlyList<X509Certificate2> certificates, SignRequest payload)
        => ResolveCertificateAsync(certificates, payload.CertIndex, payload.Thumbprint);

    private async Task<X509Certificate2?> ResolveCertificateAsync(IReadOnlyList<X509Certificate2> certificates, int? certIndex, string? thumbprint)
    {
        X509Certificate2? certificate = null;

        if (CertificateRequested is not null)
        {
            var context = new CertificateRequestContext(certificates, certIndex, thumbprint);
            foreach (Func<CertificateRequestContext, X509Certificate2?> handler in CertificateRequested.GetInvocationList())
            {
                certificate = await Task.Run(() => handler(context)).ConfigureAwait(false);
                if (certificate is not null)
                {
                    break;
                }
            }
        }

        certificate ??= DefaultCertificateResolution(certificates, certIndex, thumbprint);
        return certificate;
    }

    private static X509Certificate2? DefaultCertificateResolution(IReadOnlyList<X509Certificate2> certificates, int? certIndex, string? thumbprint)
    {
        if (certIndex.HasValue)
        {
            var index = certIndex.Value;
            if (index >= 0 && index < certificates.Count)
            {
                return certificates[index];
            }

            return null;
        }

        if (!string.IsNullOrWhiteSpace(thumbprint))
        {
            var thumb = thumbprint.Replace(" ", string.Empty, StringComparison.Ordinal);
            return certificates.FirstOrDefault(c =>
                string.Equals(c.Thumbprint, thumb, StringComparison.OrdinalIgnoreCase));
        }

        return certificates.Count == 1 ? certificates[0] : null;
    }

    private static PdfStampOptions BuildPdfStampOptions(PdfSignRequest request, X509Certificate2 certificate)
    {
        var options = new PdfStampOptions
        {
            WatermarkText = string.IsNullOrWhiteSpace(request.Watermark)
                ? "Documento assinado eletronicamente"
                : request.Watermark,
            ProtocolNumber = string.IsNullOrWhiteSpace(request.Protocol)
                ? $"NS-{DateTime.UtcNow:yyyyMMddHHmmss}"
                : request.Protocol,
            FooterNote = string.IsNullOrWhiteSpace(request.FooterNote)
                ? "Documento valido somente com assinatura digital."
                : request.FooterNote,
            Reason = "Assinatura digital do NacionalSign",
            Location = "Brasil",
            SignerName = certificate.GetNameInfo(X509NameType.SimpleName, false),
            SignaturePage = request.SignaturePage < 1 ? 1 : request.SignaturePage,
            SignatureRectWidth = request.SignatureWidth,
            SignatureRectHeight = request.SignatureHeight,
            SignatureRectMarginX = request.SignatureMarginX,
            SignatureRectMarginY = request.SignatureMarginY,
            SignatureFieldName = "NacionalSignSignature",
            SignatureType = string.IsNullOrWhiteSpace(request.SignatureType)
                ? "Assinatura digital ICP-Brasil"
                : request.SignatureType,
            AuthenticationMethod = string.IsNullOrWhiteSpace(request.Authentication)
                ? "Certificado digital (PIN)"
                : request.Authentication,
            CertificateDescription = string.IsNullOrWhiteSpace(request.CertificateDescription)
                ? certificate.GetNameInfo(X509NameType.SimpleName, false)
                : request.CertificateDescription,
            TokenDescription = string.IsNullOrWhiteSpace(request.TokenInfo)
                ? certificate.Issuer
                : request.TokenInfo,
            SignedAt = DateTimeOffset.Now
        };

        foreach (var action in request.Actions ?? Enumerable.Empty<string>())
        {
            if (!string.IsNullOrWhiteSpace(action))
            {
                options.Actions.Add(action.Trim());
            }
        }

        if (options.Actions.Count == 0)
        {
            options.Actions.Add("Documento enviado pelo NacionalSign.");
            options.Actions.Add("Assinatura digital aplicada com validade juridica.");
        }

        return options;
    }

    public void Dispose()
    {
        _cts.Cancel();
        _cts.Dispose();
        _startedTcs?.TrySetCanceled();
    }

    private void OnStarted() => Started?.Invoke(this, EventArgs.Empty);

    private void OnStopped() => Stopped?.Invoke(this, EventArgs.Empty);
}

public record CertificateRequestContext(IReadOnlyList<X509Certificate2> Certificates, int? CertIndex, string? Thumbprint);

public record PinRequestContext(string Subject, string Issuer);
