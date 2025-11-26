using System.Security.Cryptography.X509Certificates;

namespace SigningAgentPrototype.Services;

public class CertificateService
{
    /// <summary>
    ///     Retorna certificados do repositório pessoal do usuário atual.
    /// </summary>
    public virtual List<X509Certificate2> GetCertificates(bool includeOnlyWithPrivateKey = true)
    {
        using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
        store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);

        var certificates = store.Certificates.Cast<X509Certificate2>();
        if (includeOnlyWithPrivateKey)
        {
            certificates = certificates.Where(c => c.HasPrivateKey);
        }

        return certificates
            .OrderByDescending(c => c.NotAfter)
            .ToList();
    }
}
