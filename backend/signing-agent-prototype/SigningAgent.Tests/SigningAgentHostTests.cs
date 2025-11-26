using System.Net.Http;
using System.Net.Http.Json;
using System.Security.Cryptography.Pkcs;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using SigningAgentPrototype;
using SigningAgentPrototype.Models;
using SigningAgentPrototype.Services;

namespace SigningAgent.Tests;

public class SigningAgentHostTests
{
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };

    [Fact]
    public async Task StatusEndpoint_ReturnsCertificateCount()
    {
        using var certificate = CreateCertificate();
        var fakeService = new FakeCertificateService(new[] { certificate });
        var port = GetFreeTcpPort();
        var host = new SigningAgentHost(port, services =>
        {
            services.AddSingleton<CertificateService>(_ => fakeService);
        });

        try
        {
            host.Start();
            await host.WaitUntilStartedAsync(TimeSpan.FromSeconds(10));

            using var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            using var response = await client.GetAsync("/status");
            var content = await response.Content.ReadAsStringAsync();
            Assert.True(response.IsSuccessStatusCode, content);

            var status = JsonSerializer.Deserialize<StatusResponse>(content, JsonOptions);
            Assert.NotNull(status);
            Assert.Equal("ok", status!.status);
            Assert.Equal(1, status.certificates);
        }
        finally
        {
            await host.StopAsync();
            host.Dispose();
        }
    }

    [Fact]
    public async Task SignEndpoint_ReturnsSignatureForPayload()
    {
        using var certificate = CreateCertificate();
        var fakeService = new FakeCertificateService(new[] { certificate });
        var port = GetFreeTcpPort();
        var host = new SigningAgentHost(port, services =>
        {
            services.AddSingleton<CertificateService>(_ => fakeService);
        });

        try
        {
            host.Start();
            await host.WaitUntilStartedAsync(TimeSpan.FromSeconds(10));

            using var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}") };

            var payloadBytes = Encoding.UTF8.GetBytes("conteúdo de teste");
            var payloadBase64 = Convert.ToBase64String(payloadBytes);

            using var response = await client.PostAsJsonAsync("/sign", new
            {
                certIndex = 0,
                payload = payloadBase64,
                detached = false
            });

            var content = await response.Content.ReadAsStringAsync();
            Assert.True(response.IsSuccessStatusCode, content);

            var body = JsonSerializer.Deserialize<SignResponse>(content, JsonOptions);
            Assert.NotNull(body);
            Assert.False(string.IsNullOrWhiteSpace(body!.Signature));
            Assert.Equal(certificate.Subject, body.CertificateSubject);
            Assert.Equal(certificate.SerialNumber, body.CertificateSerial);
        }
        finally
        {
            await host.StopAsync();
            host.Dispose();
        }
    }

    [Fact]
    public async Task SignEndpoint_WhenPinRequired_RequestsAndUsesPin()
    {
        using var certificate = CreateCertificate();
        var fakeCertService = new FakeCertificateService(new[] { certificate });
        var signingService = new FakePinSigningService(expectedPin: "1234");
        var port = GetFreeTcpPort();
        var host = new SigningAgentHost(port, services =>
        {
            services.AddSingleton<CertificateService>(_ => fakeCertService);
            services.AddSingleton<SigningService>(_ => signingService);
        });

        host.PinRequested += _ => Task.FromResult<string?>("1234");

        try
        {
            host.Start();
            await host.WaitUntilStartedAsync(TimeSpan.FromSeconds(10));

            using var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            var payload = Convert.ToBase64String(Encoding.UTF8.GetBytes("dados"));

            using var response = await client.PostAsJsonAsync("/sign", new { certIndex = 0, payload, detached = false });
            var body = await response.Content.ReadAsStringAsync();

            Assert.True(response.IsSuccessStatusCode, body);
            Assert.True(signingService.PinWasRequested);
            Assert.True(signingService.SignatureCompleted);
        }
        finally
        {
            await host.StopAsync();
            host.Dispose();
        }
    }

    [Fact]
    public async Task SignEndpoint_WhenPinIsWrong_ReturnsBadRequest()
    {
        using var certificate = CreateCertificate();
        var fakeCertService = new FakeCertificateService(new[] { certificate });
        var signingService = new FakePinSigningService(expectedPin: "1234");
        var port = GetFreeTcpPort();
        var host = new SigningAgentHost(port, services =>
        {
            services.AddSingleton<CertificateService>(_ => fakeCertService);
            services.AddSingleton<SigningService>(_ => signingService);
        });

        host.PinRequested += _ => Task.FromResult<string?>("9999");

        try
        {
            host.Start();
            await host.WaitUntilStartedAsync(TimeSpan.FromSeconds(10));

            using var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            var payload = Convert.ToBase64String(Encoding.UTF8.GetBytes("dados"));

            using var response = await client.PostAsJsonAsync("/sign", new { certIndex = 0, payload, detached = false });
            var content = await response.Content.ReadAsStringAsync();

            Assert.Equal(System.Net.HttpStatusCode.BadRequest, response.StatusCode);
            Assert.Contains("PIN", content, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            await host.StopAsync();
            host.Dispose();
        }
    }

    [Fact]
    public async Task SignEndpoint_WhenPinNotProvided_ReturnsBadRequest()
    {
        using var certificate = CreateCertificate();
        var fakeCertService = new FakeCertificateService(new[] { certificate });
        var signingService = new FakePinSigningService(expectedPin: "1234");
        var port = GetFreeTcpPort();
        var host = new SigningAgentHost(port, services =>
        {
            services.AddSingleton<CertificateService>(_ => fakeCertService);
            services.AddSingleton<SigningService>(_ => signingService);
        });

        host.PinRequested += _ => Task.FromResult<string?>(null);

        try
        {
            host.Start();
            await host.WaitUntilStartedAsync(TimeSpan.FromSeconds(10));

            using var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            var payload = Convert.ToBase64String(Encoding.UTF8.GetBytes("dados"));

            using var response = await client.PostAsJsonAsync("/sign", new { certIndex = 0, payload, detached = false });
            var content = await response.Content.ReadAsStringAsync();

            Assert.Equal(System.Net.HttpStatusCode.BadRequest, response.StatusCode);
            Assert.Contains("PIN", content, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            await host.StopAsync();
            host.Dispose();
        }
    }

    [Fact]
    public async Task PdfSignEndpoint_ReturnsSignedPdf()
    {
        using var certificate = CreateCertificate();
        var fakeService = new FakeCertificateService(new[] { certificate });
        var port = GetFreeTcpPort();
        var host = new SigningAgentHost(port, services =>
        {
            services.AddSingleton<CertificateService>(_ => fakeService);
        });

        try
        {
            host.Start();
            await host.WaitUntilStartedAsync(TimeSpan.FromSeconds(10));

            using var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}") };
            var request = new
            {
                certIndex = 0,
                payload = Convert.ToBase64String(CreateSamplePdf()),
                protocol = "TEST-0001",
                actions = new[] { "Documento recebido", "Assinado eletronicamente" },
                signatureType = "Assinatura digital ICP-Brasil",
                authentication = "Certificado digital (PIN)"
            };

            using var response = await client.PostAsJsonAsync("/sign/pdf", request);
            var bodyText = await response.Content.ReadAsStringAsync();
            Assert.True(response.IsSuccessStatusCode, bodyText);

            var body = JsonSerializer.Deserialize<PdfSignResponse>(bodyText, JsonOptions);
            Assert.NotNull(body);
            Assert.False(string.IsNullOrWhiteSpace(body!.Pdf));

            var signedPdf = Convert.FromBase64String(body.Pdf);
            Assert.True(signedPdf.Length > 0);
        }
        finally
        {
            await host.StopAsync();
            host.Dispose();
        }
    }


    private static int GetFreeTcpPort()
    {
        var listener = new TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        var port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    private static X509Certificate2 CreateCertificate()
    {
        using var rsa = RSA.Create(2048);
        var request = new CertificateRequest("CN=SigningAgent Test", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        return request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddHours(1));
    }

    private sealed record StatusResponse(string status, string version, int certificates);

    private sealed class FakeCertificateService : CertificateService
    {
        private readonly List<X509Certificate2> _certificates;

        public FakeCertificateService(IEnumerable<X509Certificate2> certificates)
        {
            _certificates = certificates.ToList();
        }

        public override List<X509Certificate2> GetCertificates(bool includeOnlyWithPrivateKey = true)
        {
            var source = includeOnlyWithPrivateKey
                ? _certificates.Where(c => c.HasPrivateKey)
                : _certificates;

            return source.Select(c => new X509Certificate2(c.Export(X509ContentType.Pfx))).ToList();
        }
    }

    private static byte[] CreateSamplePdf()
    {
        const string pdf = @"%PDF-1.4
1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj
2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj
3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj
4 0 obj <</Length 44>> stream
BT /F1 24 Tf 72 700 Td (Sample PDF) Tj ET
endstream
endobj
5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj
xref
0 6
0000000000 65535 f
0000000010 00000 n
0000000067 00000 n
0000000125 00000 n
0000000270 00000 n
0000000395 00000 n
trailer <</Size 6 /Root 1 0 R>>
startxref
447
%%EOF";
        return Encoding.ASCII.GetBytes(pdf);
    }

    private sealed class FakePinSigningService : SigningService
    {
        private readonly string _expectedPin;
        private bool _pinRequested;
        private bool _completed;

        public FakePinSigningService(string expectedPin)
        {
            _expectedPin = expectedPin;
        }

        public bool PinWasRequested => _pinRequested;

        public bool SignatureCompleted => _completed;

        public override SignedCms SignBytes(byte[] content, X509Certificate2 certificate, bool detached, string? pin = null)
        {
            if (!_pinRequested)
            {
                _pinRequested = true;
                throw new PinRequiredException("PIN necessario.");
            }

            if (pin != _expectedPin)
            {
                throw new PinValidationException("PIN invalido.");
            }

            _completed = true;
            return base.SignBytes(content, certificate, detached);
        }
    }
}

