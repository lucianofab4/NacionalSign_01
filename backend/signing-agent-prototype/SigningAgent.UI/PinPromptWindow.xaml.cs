using System.Windows;

namespace SigningAgent.UI;

public partial class PinPromptWindow : Window
{
    public string? Pin { get; private set; }

    public PinPromptWindow(string subject)
    {
        InitializeComponent();
        MessageText.Text = $"Informe o PIN para o certificado:\n{subject}";
        Loaded += (_, _) => PinBox.Focus();
    }

    private void ConfirmClick(object sender, RoutedEventArgs e)
    {
        Pin = PinBox.Password;
        DialogResult = !string.IsNullOrWhiteSpace(Pin);
    }
}
