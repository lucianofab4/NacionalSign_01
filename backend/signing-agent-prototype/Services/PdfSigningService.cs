using iText.IO.Font.Constants;
using iText.Kernel.Colors;
using iText.Kernel.Font;
using iText.Kernel.Geom;
using iText.Kernel.Pdf;
using iText.Kernel.Pdf.Canvas;
using iText.Layout;
using iText.Layout.Element;
using iText.Layout.Properties;
using iText.Signatures;
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography.Pkcs;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace SigningAgentPrototype.Services;

public class PdfSigningService
{
    private readonly SigningService _signingService;

    public PdfSigningService(SigningService signingService)
    {
        _signingService = signingService;
    }

    public void SignPdf(string inputPath, string outputPath, X509Certificate2 certificate, PdfStampOptions options, string? pin = null)
    {
        ArgumentException.ThrowIfNullOrEmpty(inputPath);
        ArgumentException.ThrowIfNullOrEmpty(outputPath);
        ArgumentNullException.ThrowIfNull(options);

        if (!File.Exists(inputPath))
        {
            throw new FileNotFoundException("PDF de origem nao encontrado para assinatura.", inputPath);
        }

        var tempStampedPath = System.IO.Path.GetTempFileName();
        try
        {
            ApplyVisualStamp(inputPath, tempStampedPath, options);
            ApplyDigitalSignature(tempStampedPath, outputPath, certificate, options, pin);
        }
        finally
        {
            try
            {
                if (File.Exists(tempStampedPath))
                {
                    File.Delete(tempStampedPath);
                }
            }
            catch
            {
                // best effort
            }
        }
    }

    private static void ApplyVisualStamp(string inputPath, string outputPath, PdfStampOptions options)
    {
        using var reader = new PdfReader(inputPath);
        using var outputStream = new FileStream(outputPath, FileMode.Create, FileAccess.Write, FileShare.None);
        using var writer = new PdfWriter(outputStream, new WriterProperties());
        using var pdfDoc = new PdfDocument(reader, writer);

        var totalPages = pdfDoc.GetNumberOfPages();
        var font = PdfFontFactory.CreateFont(StandardFonts.HELVETICA);
        var headerColor = new DeviceRgb(120, 135, 180);

        for (var pageIndex = 1; pageIndex <= totalPages; pageIndex++)
        {
            var page = pdfDoc.GetPage(pageIndex);
            var pageSize = page.GetPageSize();
            using var canvas = new Canvas(new PdfCanvas(page.NewContentStreamAfter(), page.GetResources(), pdfDoc), pageSize);
            DrawHeader(canvas, pageSize, pageIndex, options.WatermarkText, font, headerColor);
        }

        if (!string.IsNullOrWhiteSpace(options.ProtocolNumber) || options.Actions.Count > 0 || !string.IsNullOrWhiteSpace(options.FooterNote))
        {
            var protocolPage = pdfDoc.AddNewPage(PageSize.A4);
            using var protocolCanvas = new Canvas(new PdfCanvas(protocolPage), protocolPage.GetPageSize());
            DrawProtocolPage(protocolCanvas, protocolPage.GetPageSize(), options, font);
        }
    }

    private static void DrawHeader(Canvas canvas, Rectangle pageSize, int pageNumber, string text, PdfFont font, Color color)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return;
        }

        var header = new Paragraph(text)
            .SetFont(font)
            .SetFontSize(6)
            .SetFontColor(color)
            .SetTextAlignment(TextAlignment.LEFT);

        canvas.ShowTextAligned(header,
            pageSize.GetLeft() + 24,
            pageSize.GetTop() - 12,
            pageNumber,
            TextAlignment.LEFT,
            VerticalAlignment.TOP,
            0);
    }

    private static void DrawProtocolPage(Canvas canvas, Rectangle pageSize, PdfStampOptions options, PdfFont font)
    {
        var currentY = pageSize.GetTop() - 72;
        var centerX = pageSize.GetWidth() / 2f;
        var leftX = pageSize.GetLeft() + 72;

        currentY = WriteTitle(canvas, centerX, currentY, "Protocolo de Assinatura", font, 20);

        if (!string.IsNullOrWhiteSpace(options.ProtocolNumber))
        {
            currentY = WriteLine(canvas, leftX, currentY, $"Numero do protocolo: {options.ProtocolNumber}", font, 12, ColorConstants.DARK_GRAY);
            currentY -= 4;
        }

        if (!string.IsNullOrWhiteSpace(options.SignerName) ||
            !string.IsNullOrWhiteSpace(options.Reason) ||
            !string.IsNullOrWhiteSpace(options.Location))
        {
            currentY = WriteLine(canvas, leftX, currentY, "Informacoes da assinatura", font, 12, ColorConstants.BLACK, bold: true);
            if (!string.IsNullOrWhiteSpace(options.SignerName))
            {
                currentY = WriteLine(canvas, leftX, currentY, $"Assinado por: {options.SignerName}", font, 11);
            }
            if (!string.IsNullOrWhiteSpace(options.Reason))
            {
                currentY = WriteLine(canvas, leftX, currentY, $"Motivo: {options.Reason}", font, 11);
            }
            if (!string.IsNullOrWhiteSpace(options.Location))
            {
                currentY = WriteLine(canvas, leftX, currentY, $"Local: {options.Location}", font, 11);
            }
            currentY = WriteLine(canvas, leftX, currentY, $"Data/Hora: {options.SignedAt.ToLocalTime():dd/MM/yyyy HH:mm:ss}", font, 11);
            currentY -= 8;
        }

        if (!string.IsNullOrWhiteSpace(options.SignatureType) ||
            !string.IsNullOrWhiteSpace(options.AuthenticationMethod) ||
            !string.IsNullOrWhiteSpace(options.CertificateDescription) ||
            !string.IsNullOrWhiteSpace(options.TokenDescription))
        {
            currentY = WriteLine(canvas, leftX, currentY, "Detalhes tecnicos", font, 12, ColorConstants.BLACK, bold: true);
            if (!string.IsNullOrWhiteSpace(options.SignatureType))
            {
                currentY = WriteLine(canvas, leftX, currentY, $"Tipo da assinatura: {options.SignatureType}", font, 11);
            }
            if (!string.IsNullOrWhiteSpace(options.AuthenticationMethod))
            {
                currentY = WriteLine(canvas, leftX, currentY, $"Usuario e senha: {options.AuthenticationMethod}", font, 11);
            }
            if (!string.IsNullOrWhiteSpace(options.CertificateDescription))
            {
                currentY = WriteLine(canvas, leftX, currentY, $"Certificado digital: {options.CertificateDescription}", font, 11);
            }
            if (!string.IsNullOrWhiteSpace(options.TokenDescription))
            {
                var tokenLines = WrapCommaSeparatedText($"Token: {options.TokenDescription}");
                foreach (var tokenLine in tokenLines)
                {
                    currentY = WriteLine(canvas, leftX, currentY, tokenLine, font, 11);
                }
            }
            currentY -= 8;
        }

        if (options.Actions.Count > 0)
        {
            currentY = WriteLine(canvas, leftX, currentY, "Acoes executadas:", font, 12, ColorConstants.BLACK, bold: true);
            foreach (var action in options.Actions)
            {
                currentY = WriteLine(canvas, leftX, currentY, $"- {action}", font, 11);
            }
        }

        if (!string.IsNullOrWhiteSpace(options.FooterNote))
        {
            var footerParagraph = new Paragraph(options.FooterNote)
                .SetFont(font)
                .SetFontSize(10)
                .SetFontColor(ColorConstants.GRAY);

            canvas.ShowTextAligned(footerParagraph, centerX, pageSize.GetBottom() + 48, TextAlignment.CENTER);
        }
    }

    private void ApplyDigitalSignature(string inputPath, string outputPath, X509Certificate2 certificate, PdfStampOptions options, string? pin)
    {
        using var reader = new PdfReader(inputPath);
        using var signedStream = new FileStream(outputPath, FileMode.Create, FileAccess.Write);
        var signer = new PdfSigner(reader, signedStream, new StampingProperties().UseAppendMode());

        var appearance = signer.GetSignatureAppearance();
        appearance.SetReuseAppearance(false);
        appearance.SetLayer2Text(string.Empty);

        var page = signer.GetDocument().GetPage(options.SignaturePage);
        var pageSize = page.GetPageSize();
        var rect = new Rectangle(
            pageSize.GetRight() - options.SignatureRectWidth - options.SignatureRectMarginX,
            pageSize.GetBottom() + options.SignatureRectMarginY,
            options.SignatureRectWidth,
            options.SignatureRectHeight);

        appearance.SetPageRect(rect);
        appearance.SetPageNumber(options.SignaturePage);

        signer.SetFieldName(options.SignatureFieldName);

        var container = new SigningAgentExternalSignatureContainer(_signingService, certificate, pin);
        signer.SignExternalContainer(container, 8192);
    }

    private static float WriteTitle(Canvas canvas, float centerX, float y, string text, PdfFont font, float fontSize)
    {
        var paragraph = new Paragraph(text)
            .SetFont(font)
            .SetFontSize(fontSize)
            .SetBold()
            .SetFontColor(ColorConstants.BLACK);

        canvas.ShowTextAligned(paragraph, centerX, y, TextAlignment.CENTER);
        return y - (fontSize + 20);
    }

    private static float WriteLine(Canvas canvas, float x, float y, string text, PdfFont font, float fontSize,
        Color? color = null, bool bold = false)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return y;
        }

        var paragraph = new Paragraph(text)
            .SetFont(font)
            .SetFontSize(fontSize)
            .SetFontColor(color ?? ColorConstants.BLACK);

        if (bold)
        {
            paragraph.SetBold();
        }

        canvas.ShowTextAligned(paragraph, x, y, TextAlignment.LEFT);
        return y - (fontSize + 10);
    }

    private static IEnumerable<string> WrapCommaSeparatedText(string text, int maxLength = 90)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            yield break;
        }

        var parts = text.Split(',');
        var builder = new StringBuilder();

        foreach (var rawPart in parts)
        {
            var part = rawPart.Trim();
            if (part.Length == 0)
            {
                continue;
            }

            var separator = builder.Length == 0 ? string.Empty : ", ";
            if (builder.Length > 0 && builder.Length + separator.Length + part.Length > maxLength)
            {
                yield return builder.ToString();
                builder.Clear();
                separator = string.Empty;
            }

            if (builder.Length > 0)
            {
                builder.Append(", ");
            }
            builder.Append(part);
        }

        if (builder.Length > 0)
        {
            yield return builder.ToString();
        }
    }

    private sealed class SigningAgentExternalSignatureContainer : IExternalSignatureContainer
    {
        private readonly SigningService _signingService;
        private readonly X509Certificate2 _certificate;
        private readonly string? _pin;

        public SigningAgentExternalSignatureContainer(SigningService signingService, X509Certificate2 certificate, string? pin)
        {
            _signingService = signingService;
            _certificate = certificate;
            _pin = pin;
        }

        public void ModifySigningDictionary(PdfDictionary signDic)
        {
            signDic.Put(PdfName.Filter, PdfName.Adobe_PPKLite);
            signDic.Put(PdfName.SubFilter, PdfName.ETSI_CAdES_DETACHED);
        }

        public byte[] Sign(Stream data)
        {
            using var buffer = new MemoryStream();
            data.CopyTo(buffer);
            var toSign = buffer.ToArray();
            var signedCms = _signingService.SignBytes(toSign, _certificate, detached: true, _pin);
            return signedCms.Encode();
        }
    }
}



