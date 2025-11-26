using System;
using System;
using System.Collections.Generic;

namespace SigningAgentPrototype.Services;

public class PdfStampOptions
{
    public string WatermarkText { get; set; } = "Documento assinado eletronicamente";

    public string ProtocolNumber { get; set; } = string.Empty;

    public IList<string> Actions { get; set; } = new List<string>();

    public string FooterNote { get; set; } = "Documento vlido somente com assinatura digital.";

    public string Reason { get; set; } = "Assinatura digital do NacionalSign";

    public string Location { get; set; } = "Brasil";

    public string SignerName { get; set; } = string.Empty;

    public int SignaturePage { get; set; } = 1;

    public float SignatureRectWidth { get; set; } = 250;

    public float SignatureRectHeight { get; set; } = 120;

    public float SignatureRectMarginX { get; set; } = 36;

    public float SignatureRectMarginY { get; set; } = 36;

    public string SignatureFieldName { get; set; } = "NacionalSignSignature";

    public string SignatureType { get; set; } = "Assinatura digital ICP-Brasil";

    public string AuthenticationMethod { get; set; } = "Certificado digital (PIN)";

    public string CertificateDescription { get; set; } = string.Empty;

    public string TokenDescription { get; set; } = "Dispositivo criptografico";

    public DateTimeOffset SignedAt { get; set; } = DateTimeOffset.UtcNow;
}

