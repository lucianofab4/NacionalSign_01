namespace SigningAgentPrototype.Models;

public class SignRequest
{
    public int? CertIndex { get; set; }
    public string? Thumbprint { get; set; }
    public string Payload { get; set; } = string.Empty;
    public bool Detached { get; set; } = true;
}

public class SignResponse
{
    public string Signature { get; set; } = string.Empty;
    public string CertificateSubject { get; set; } = string.Empty;
    public string CertificateSerial { get; set; } = string.Empty;
    public string CertificateIssuer { get; set; } = string.Empty;
    public DateTime SignedAt { get; set; } = DateTime.UtcNow;
}
