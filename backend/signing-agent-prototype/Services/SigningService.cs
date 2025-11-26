using System;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Cryptography.Pkcs;
using System.Security.Cryptography.X509Certificates;

namespace SigningAgentPrototype.Services;

public class SigningService
{
    /// <summary>
    ///     Assina o arquivo informado e gera um PKCS#7 (<arquivo>.p7s).
    /// </summary>
    public string SignFileWithCertificate(string filePath, X509Certificate2 certificate, string? pin = null)
    {
        ArgumentNullException.ThrowIfNull(certificate);

        if (!File.Exists(filePath))
        {
            throw new FileNotFoundException("Arquivo não encontrado para assinatura.", filePath);
        }

        var fileBytes = File.ReadAllBytes(filePath);
        var signedCms = SignBytes(fileBytes, certificate, detached: true, pin);

        var outputPath = $"{filePath}.p7s";
        File.WriteAllBytes(outputPath, signedCms.Encode());
        return outputPath;
    }

    /// <summary>
    ///     Assina bytes arbitrários usando SignedCms.
    /// </summary>
    public virtual SignedCms SignBytes(byte[] content, X509Certificate2 certificate, bool detached, string? pin = null)
    {
        ArgumentNullException.ThrowIfNull(content);
        ArgumentNullException.ThrowIfNull(certificate);

        if (!string.IsNullOrWhiteSpace(pin))
        {
            ApplyPin(certificate, pin);
        }

        var cms = new SignedCms(new ContentInfo(content), detached);
        var signer = new CmsSigner(SubjectIdentifierType.IssuerAndSerialNumber, certificate)
        {
            IncludeOption = X509IncludeOption.EndCertOnly,
            DigestAlgorithm = new Oid(Oids.Sha256)
        };

        try
        {
            cms.ComputeSignature(signer, silent: true);
            return cms;
        }
        catch (CryptographicException ex) when (string.IsNullOrWhiteSpace(pin) && RequiresPin(ex))
        {
            throw new PinRequiredException("O dispositivo exige a digitação do PIN antes de continuar.", ex);
        }
        catch (CryptographicException ex) when (!string.IsNullOrWhiteSpace(pin) && IsInvalidPin(ex))
        {
            throw new PinValidationException("PIN inválido ou recusado pelo token.", ex);
        }
    }

    private static void ApplyPin(X509Certificate2 certificate, string pin)
    {
        try
        {
            var method = typeof(X509Certificate2).GetMethod(
                "SetPinForPrivateKey",
                BindingFlags.Instance | BindingFlags.Public,
                binder: null,
                types: new[] { typeof(string) },
                modifiers: null);
            if (method is null)
            {
                throw new PinConfigurationException("A plataforma atual não disponibiliza SetPinForPrivateKey.");
            }

            method.Invoke(certificate, new object?[] { pin });
        }
        catch (TargetInvocationException ex)
        {
            throw new PinConfigurationException("Falha ao aplicar o PIN no dispositivo.", ex.InnerException ?? ex);
        }
        catch (Exception ex) when (ex is NotSupportedException or InvalidOperationException)
        {
            throw new PinConfigurationException("Não foi possível aplicar o PIN ao certificado selecionado.", ex);
        }
    }

    private static bool RequiresPin(CryptographicException ex)
    {
        var hresult = ex.HResult;
        return hresult switch
        {
            unchecked((int)0x80090016) => true, // NTE_BAD_KEYSET
            unchecked((int)0x8010001C) => true, // SCARD_W_CANCELLED_BY_USER
            unchecked((int)0x8010006B) => true, // SCARD_W_WRONG_CHV
            _ => ex.Message.Contains("pin", StringComparison.OrdinalIgnoreCase)
                 || ex.Message.Contains("senha", StringComparison.OrdinalIgnoreCase)
        };
    }

    private static bool IsInvalidPin(CryptographicException ex)
    {
        var hresult = ex.HResult;
        return hresult == unchecked((int)0x8010006B)
            || ex.Message.Contains("pin", StringComparison.OrdinalIgnoreCase)
            || ex.Message.Contains("senha", StringComparison.OrdinalIgnoreCase);
    }
}

internal static class Oids
{
    public const string Sha256 = "2.16.840.1.101.3.4.2.1";
}
