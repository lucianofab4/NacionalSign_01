namespace SigningAgentPrototype.Models;

public class PdfSignRequest
{
    public int? CertIndex { get; set; }

    public string? Thumbprint { get; set; }

    /// <summary>
    ///     PDF original em Base64.
    /// </summary>
    public string Payload { get; set; } = string.Empty;

    public string? Protocol { get; set; }

    public string? Watermark { get; set; }

    public string? FooterNote { get; set; }

    public IEnumerable<string>? Actions { get; set; }

    public string? SignatureType { get; set; }

    public string? Authentication { get; set; }

    public string? CertificateDescription { get; set; }

    public string? TokenInfo { get; set; }

    public int SignaturePage { get; set; } = 1;

    public float SignatureWidth { get; set; } = 250f;

    public float SignatureHeight { get; set; } = 120f;

    public float SignatureMarginX { get; set; } = 36f;

    public float SignatureMarginY { get; set; } = 36f;
}
