namespace SigningAgentPrototype.Services;

public class PinRequiredException : Exception
{
    public PinRequiredException(string message, Exception? inner = null)
        : base(message, inner)
    {
    }
}
