using System.Security.Cryptography.X509Certificates;

namespace SigningAgent.UI;

public class DisplayCertificate
{
    public DisplayCertificate(X509Certificate2 certificate, int index)
    {
        Certificate = certificate;
        Index = index;
    }

    public X509Certificate2 Certificate { get; }

    public int Index { get; }

    public string Subject => Certificate.Subject;

    public string Issuer => Certificate.Issuer;

    public string SerialNumber => Certificate.SerialNumber;

    public string Thumbprint => Certificate.Thumbprint;

    public string NotAfter => Certificate.NotAfter.ToString("dd/MM/yyyy HH:mm");
}
