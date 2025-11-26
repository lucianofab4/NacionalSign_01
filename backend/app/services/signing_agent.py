from __future__ import annotations

import base64
import json
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

    # ======================================================================================
    #     REQUISIÇÃO ROBUSTA — TRATAMENTO SEGURO E COMPATÍVEL COM O DOCUMENTSERVICE
    # ======================================================================================
    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"

        try:
            response = httpx.request(
                method,
                url,
                json=json,
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise SigningAgentError(f"Falha ao conectar com o agente local: {exc}") from exc

        content = response.content

        # -----------------------------
        # ERRO HTTP
        # -----------------------------
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = {"error": response.text or content.decode("latin1", errors="ignore")}
            msg = str(payload.get("error") or payload.get("detail") or "Erro no agente de assinatura.")
            raise SigningAgentError(msg, details=payload, status_code=response.status_code)

        # -----------------------------
        # JSON normal
        # -----------------------------
        try:
            return response.json()
        except Exception:
            pass

        # -----------------------------
        # JSON como texto
        # -----------------------------
        try:
            txt = content.decode("utf-8")
            return json.loads(txt)
        except Exception:
            pass

        # -----------------------------
        # Conteúdo PDF puro
        # -----------------------------
        if content.startswith(b"%PDF"):
            return {
                "pdf": base64.b64encode(content).decode("utf-8"),
                "p7s": None,
            }

        # -----------------------------
        # Conteúdo XML puro (ex: PKCS#7 encapsulado)
        # -----------------------------
        stripped = content.strip()
        if stripped.startswith(b"<") and stripped.endswith(b">"):
            return {
                "pdf": None,
                "p7s": base64.b64encode(content).decode("utf-8"),
            }

        # -----------------------------
        # Conteúdo BASE64 que contém PDF
        # -----------------------------
        try:
            raw = base64.b64decode(content)
            if raw.startswith(b"%PDF"):
                return {
                    "pdf": content.decode("utf-8"),
                    "p7s": None,
                }
        except Exception:
            pass

        # -----------------------------
        # IMPOSSÍVEL DETERMINAR → erro
        # -----------------------------
        raise SigningAgentError(
            "Resposta inválida do agente de assinatura.",
            details={"raw": content[:200]},
        )

    # ======================================================================================
    #     MÉTODOS PÚBLICOS
    # ======================================================================================
    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status")

    def list_certificates(self) -> Iterable[dict[str, Any]]:
        data = self._request("GET", "/certificates")
        return data if isinstance(data, list) else data.get("items", [])

    def sign_pdf(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/sign/pdf", json=payload)


# ======================================================================================
#     PAYLOAD DO AGENTE
# ======================================================================================

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
    payload: dict[str, Any] = {
        "payload": base64.b64encode(pdf_bytes).decode("utf-8")
    }

    def add_if(k, v):
        if v is not None:
            payload[k] = v

    add_if("certIndex", cert_index)
    add_if("thumbprint", thumbprint)
    add_if("protocol", protocol)
    add_if("watermark", watermark)
    add_if("footerNote", footer_note)
    add_if("signatureType", signature_type)
    add_if("authentication", authentication)
    add_if("certificateDescription", certificate_description)
    add_if("tokenInfo", token_info)
    add_if("signaturePage", signature_page)
    add_if("signatureWidth", signature_width)
    add_if("signatureHeight", signature_height)
    add_if("signatureMarginX", signature_margin_x)
    add_if("signatureMarginY", signature_margin_y)

    if actions:
        payload["actions"] = [x for x in actions if x]

    return payload


# ======================================================================================
#     DECODIFICAÇÃO SEGURA (PDF + PKCS7)
# ======================================================================================

def decode_agent_pdf(response: dict[str, Any]) -> dict[str, bytes | None]:
    if not isinstance(response, dict):
        raise SigningAgentError("Resposta inválida do agente: esperado JSON dict.")

    # --- PDF ---
    pdf_b64 = (
        response.get("pdf")
        or response.get("Pdf")
        or response.get("PDF")
    )

    if not pdf_b64:
        raise SigningAgentError("Agente não retornou o PDF assinado.")

    try:
        pdf_bytes = base64.b64decode(pdf_b64)
    except Exception as exc:
        raise SigningAgentError("PDF retornado está corrompido (base64 inválido).") from exc

    # --- PKCS#7 ---
    p7s_source = (
        response.get("p7s")
        or response.get("P7s")          # <── ADICIONADO (fundamental)
        or response.get("pkcs7")
        or response.get("Pkcs7")
        or response.get("signature")
        or response.get("SignedData")
        or response.get("signedData")
        or None
    )

    p7s_bytes: bytes | None = None
    raw_candidate: bytes | None = None

    if isinstance(p7s_source, str):
        try:
            raw_candidate = base64.b64decode(p7s_source)
        except Exception:
            stripped = p7s_source.strip()
            if stripped.startswith("<") and stripped.endswith(">"):
                p7s_bytes = stripped.encode("utf-8")
    elif isinstance(p7s_source, (bytes, bytearray)):
        raw_candidate = bytes(p7s_source)

    if p7s_bytes is None and raw_candidate:
        p7s_bytes = raw_candidate

    return {
        "pdf": pdf_bytes,
        "p7s": p7s_bytes,
    }
