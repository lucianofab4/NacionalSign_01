namespace SigningAgentPrototype.Models;

public class PdfSignResponse
{
    /// <summary>
    ///     PDF final em Base64.
    /// </summary>
    public string Pdf { get; set; } = string.Empty;

    public string Protocol { get; set; } = string.Empty;

    public string SignatureType { get; set; } = string.Empty;

    public string Authentication { get; set; } = string.Empty;

    /// <summary>
    ///     Conteúdo PKCS#7 em Base64 (opcional).
    /// </summary>
    public string? P7s { get; set; }
}
