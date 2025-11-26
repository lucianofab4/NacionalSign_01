namespace SigningAgentPrototype.Services;

public class PinConfigurationException : Exception
{
    public PinConfigurationException(string message, Exception? inner = null)
        : base(message, inner)
    {
    }
}
