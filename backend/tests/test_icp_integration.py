import pytest

from app.services.icp import IcpIntegrationService
from app.core.config import settings

def test_icp_sign_and_timestamp(tmp_path):
    # Gera um PDF simples para teste
    from reportlab.pdfgen import canvas
    pdf_path = tmp_path / "teste.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(100, 750, "Teste ICP NacionalSign")
    c.save()
    pdf_bytes = pdf_path.read_bytes()

    # Instancia serviço ICP com configs reais
    icp = IcpIntegrationService.from_settings(settings)
    # Aplica timestamp e assinatura
    result = icp.apply_security(pdf_bytes, reason="Teste ICP", location="Brasil", request_timestamp=True)
    # Salva PDF assinado
    signed_path = tmp_path / "teste_assinado.pdf"
    signed_path.write_bytes(result.signed_pdf)

    print("SHA256 PDF assinado:", result.sha256)
    print("Timestamp:", result.timestamp)
    print("Warnings:", result.warnings)
    if "signer-missing" in (result.warnings or []):
        pytest.skip("ICP certificate not configured for signing.")
    assert result.signed_pdf != pdf_bytes
    assert result.sha256
