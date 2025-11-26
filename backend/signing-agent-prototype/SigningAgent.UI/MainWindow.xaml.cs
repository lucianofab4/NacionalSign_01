using SigningAgentPrototype;
using SigningAgentPrototype.Services;
using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Security.Cryptography.X509Certificates;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace SigningAgent.UI;

public partial class MainWindow : Window, INotifyPropertyChanged
{
    private readonly CertificateService _certificateService = new();
    private readonly SigningAgentHost _agentHost;
    private readonly DefaultCertificateStore _defaultStore = new();
    private string? _defaultThumbprint;
    private DisplayCertificate? _selectedCertificate;
    private string _agentStatus = "Inicializando agente...";

    public ObservableCollection<DisplayCertificate> Certificates { get; } = new();

    public DisplayCertificate? SelectedCertificate
    {
        get => _selectedCertificate;
        set
        {
            if (_selectedCertificate != value)
            {
                _selectedCertificate = value;
                OnPropertyChanged();
            }
        }
    }

    public string AgentStatus
    {
        get => _agentStatus;
        set
        {
            if (_agentStatus != value)
            {
                _agentStatus = value;
                OnPropertyChanged();
            }
        }
    }

    public MainWindow()
    {
        InitializeComponent();
        DataContext = this;

        _agentHost = new SigningAgentHost();
        _agentHost.Started += AgentHostStarted;
        _agentHost.Stopped += AgentHostStopped;
        _agentHost.CertificateRequested += HandleCertificateRequested;
        _agentHost.PinRequested += HandlePinRequestedAsync;

        AgentStatus = "Inicializando agente...";
        _agentHost.Start();

        _defaultThumbprint = _defaultStore.LoadDefaultThumbprint();
        RefreshCertificates();
    }

    private void RefreshCertificates()
    {
        var currentThumbprint = SelectedCertificate?.Thumbprint;

        Certificates.Clear();
        var certs = _certificateService.GetCertificates(includeOnlyWithPrivateKey: true);
        foreach (var (cert, index) in certs.Select((c, i) => (c, i)))
        {
            Certificates.Add(new DisplayCertificate(cert, index));
        }

        if (Certificates.Count == 0)
        {
            SelectedCertificate = null;
            AgentStatus = "Nenhum certificado com chave privada disponível.";
            return;
        }

        if (!string.IsNullOrWhiteSpace(currentThumbprint))
        {
            var current = Certificates.FirstOrDefault(c =>
                string.Equals(c.Thumbprint, currentThumbprint, StringComparison.OrdinalIgnoreCase));

            if (current is not null)
            {
                SelectedCertificate = current;
                return;
            }
        }

        if (!string.IsNullOrWhiteSpace(_defaultThumbprint))
        {
            var saved = Certificates.FirstOrDefault(c =>
                string.Equals(c.Thumbprint, _defaultThumbprint, StringComparison.OrdinalIgnoreCase));

            if (saved is not null)
            {
                SelectedCertificate = saved;
                return;
            }
        }

        SelectedCertificate = Certificates[0];
    }

    private X509Certificate2? HandleCertificateRequested(CertificateRequestContext context)
    {
        var candidate = SelectedCertificate;
        if (candidate is null)
        {
            return null;
        }

        return context.Certificates.FirstOrDefault(c =>
            string.Equals(c.Thumbprint, candidate.Thumbprint, StringComparison.OrdinalIgnoreCase));
    }

    private Task<string?> HandlePinRequestedAsync(PinRequestContext context)
    {
        return Dispatcher.InvokeAsync(() =>
        {
            AgentStatus = $"PIN solicitado para {context.Subject}";

            var dialog = new PinPromptWindow(context.Subject)
            {
                Owner = this
            };

            var result = dialog.ShowDialog() == true ? dialog.Pin : null;
            if (result is null)
            {
                AgentStatus = "PIN não informado.";
            }

            return result;
        }).Task;
    }

    private void RefreshClick(object sender, RoutedEventArgs e)
    {
        RefreshCertificates();
        AgentStatus = $"Lista de certificados atualizada ({Certificates.Count}).";
    }

    private void SetDefaultClick(object sender, RoutedEventArgs e)
    {
        if (SelectedCertificate is null)
        {
            MessageBox.Show("Selecione um certificado na lista.", "Agente de Assinatura", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        _defaultStore.SaveDefaultThumbprint(SelectedCertificate.Thumbprint);
        _defaultThumbprint = SelectedCertificate.Thumbprint;
        AgentStatus = $"Certificado padrão definido: {SelectedCertificate.Subject}";

        MessageBox.Show($"Certificado '{SelectedCertificate.Subject}' definido como padrão.", "Agente de Assinatura", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private void AgentHostStarted(object? sender, EventArgs e)
    {
        Dispatcher.Invoke(() =>
        {
            AgentStatus = $"Agente ouvindo em http://127.0.0.1:{_agentHost.Port}";
        });
    }

    private void AgentHostStopped(object? sender, EventArgs e)
    {
        Dispatcher.Invoke(() =>
        {
            AgentStatus = "Agente encerrado.";
        });
    }

    protected override async void OnClosing(CancelEventArgs e)
    {
        await _agentHost.StopAsync();
        base.OnClosing(e);
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
