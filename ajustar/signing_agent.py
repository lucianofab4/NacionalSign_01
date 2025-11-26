from __future__ import annotations

import base64
from typing import Any, Dict, Iterable, Optional

import httpx

from app.core.config import settings


class SigningAgentError(RuntimeError):
    """Erro de domínio quando o agente de assinatura falha ou está indisponível."""

    def __init__(
        self,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details or {}
        self.status_code = status_code


class SigningAgentClient:
    """Cliente HTTP para comunicação com o agente de assinatura local."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.signing_agent_base_url or "").rstrip("/")
        if not self._base_url:
            raise SigningAgentError("URL base do agente de assinatura não configurada.")
        self._timeout = timeout_seconds or settings.signing_agent_timeout_seconds or 10.0

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        """Executa requisição genérica ao agente local."""
        url = f"{self._base_url}{path}"
        try:
            response = httpx.request(method, url, json=json, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise SigningAgentError(f"Falha ao conectar com o agente local: {exc}") from exc

        # Trata respostas com erro HTTP
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": response.text}
            message = str(payload.get("error") or payload.get("detail") or "Erro no agente de assinatura.")
            raise SigningAgentError(message, details=payload, status_code=response.status_code)

        # Tenta retornar JSON válido
        try:
            return response.json()
        except ValueError as exc:
            raise SigningAgentError("Resposta inválida do agente de assinatura.") from exc

    def status(self) -> dict[str, Any]:
        """Retorna o status do agente de assinatura."""
        return self._request("GET", "/status")

    def list_certificates(self) -> Iterable[dict[str, Any]]:
        """Lista certificados disponíveis no agente local."""
        data = self._request("GET", "/certificates")
        if isinstance(data, list):
            return data
        return data.get("items", [])

    def sign_pdf(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Envia um PDF para ser assinado digitalmente."""
        return self._request("POST", "/sign/pdf", json=payload)


def build_sign_pdf_payload(
    *,
    pdf_bytes: bytes,
    cert_index: int | None = None,
    thumbprint: str | None = None,
    protocol: str | None = None,
    watermark: str | None = None,
    footer_note: str | None = None,
    actions: Iterable[str] | None = None,
    signature_type: str | None = None,
    authentication: str | None = None,
    certificate_description: str | None = None,
    token_info: str | None = None,
    signature_page: int | None = None,
    signature_width: float | None = None,
    signature_height: float | None = None,
    signature_margin_x: float | None = None,
    signature_margin_y: float | None = None,
) -> dict[str, Any]:
    """Monta o payload JSON que será enviado ao agente de assinatura."""
    payload: dict[str, Any] = {"payload": base64.b64encode(pdf_bytes).decode("utf-8")}

    def add_if(key: str, value: Any):
        if value is not None:
            payload[key] = value

    add_if("certIndex", cert_index)
    add_if("thumbprint", thumbprint)
    add_if("protocol", protocol)
    add_if("watermark", watermark)
    add_if("footerNote", footer_note)
    if actions:
        payload["actions"] = [item for item in actions if item]
    add_if("signatureType", signature_type)
    add_if("authentication", authentication)
    add_if("certificateDescription", certificate_description)
    add_if("tokenInfo", token_info)
    add_if("signaturePage", signature_page)
    add_if("signatureWidth", signature_width)
    add_if("signatureHeight", signature_height)
    add_if("signatureMarginX", signature_margin_x)
    add_if("signatureMarginY", signature_margin_y)

    return payload


def decode_agent_pdf(response: dict[str, Any]) -> bytes:
    """Decodifica o PDF Base64 retornado pelo agente."""
    pdf_base64 = response.get("pdf") or response.get("Pdf")
    if not isinstance(pdf_base64, str):
        raise SigningAgentError("Resposta do agente não contém o PDF final.")
    try:
        return base64.b64decode(pdf_base64)
    except ValueError as exc:
        raise SigningAgentError("PDF retornado pelo agente está corrompido.") from exc
    