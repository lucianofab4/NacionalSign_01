namespace SigningAgentPrototype.Services;

public class PinValidationException : Exception
{
    public PinValidationException(string message, Exception? inner = null)
        : base(message, inner)
    {
    }
}
