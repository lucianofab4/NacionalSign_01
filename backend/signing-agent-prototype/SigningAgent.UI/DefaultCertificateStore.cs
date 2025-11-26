using System.IO;
using System.Text.Json;

namespace SigningAgent.UI;

internal sealed class DefaultCertificateStore
{
    private const string FileName = "default-certificate.json";

    private readonly string _storePath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "SigningAgent",
        FileName);

    public string? LoadDefaultThumbprint()
    {
        try
        {
            if (!File.Exists(_storePath))
            {
                return null;
            }

            using var stream = File.OpenRead(_storePath);
            var document = JsonSerializer.Deserialize<DefaultCertificatePayload>(stream);
            return document?.Thumbprint;
        }
        catch
        {
            return null;
        }
    }

    public void SaveDefaultThumbprint(string thumbprint)
    {
        var payload = new DefaultCertificatePayload { Thumbprint = thumbprint };
        var directory = Path.GetDirectoryName(_storePath);
        if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
        {
            Directory.CreateDirectory(directory);
        }

        using var stream = File.Create(_storePath);
        JsonSerializer.Serialize(stream, payload);
    }

    private sealed class DefaultCertificatePayload
    {
        public string Thumbprint { get; set; } = string.Empty;
    }
}
