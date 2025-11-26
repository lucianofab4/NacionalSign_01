namespace SigningAgentPrototype.Pkcs11;

/// <summary>
///     Helper simplificado para interação com módulos PKCS#11.
///     A implementação real dependerá do middleware específico do token.
/// </summary>
public static class Pkcs11Helper
{
    // TODO: Implementar integração real com PKCS#11 (tokens A3).
    public static void EnsurePkcs11Available()
        => throw new NotImplementedException("Integração PKCS#11 ainda não implementada no protótipo.");
}
