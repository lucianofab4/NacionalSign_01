from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

try:  # pragma: no cover - optional dependency
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter  # type: ignore
    from pyhanko.sign import signers  # type: ignore
    from pyhanko.sign.general import PdfSigner, PdfSignatureMetadata  # type: ignore
    from pyhanko.sign.timestamps import HTTPTimeStamper  # type: ignore
except ImportError:  # pragma: no cover - pyhanko optional in dev environments
    IncrementalPdfFileWriter = None  # type: ignore
    PdfSigner = None  # type: ignore
    PdfSignatureMetadata = None  # type: ignore
    signers = None  # type: ignore
    HTTPTimeStamper = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from pypdf import PdfReader, PdfWriter  # type: ignore
except ImportError:  # pragma: no cover - optional in some environments
    PdfReader = None  # type: ignore
    PdfWriter = None  # type: ignore


@dataclass
class TimestampResult:
    authority: str
    issued_at: datetime
    token: bytes
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SignatureResult:
    signed_pdf: bytes
    sha256: str
    timestamp: Optional[TimestampResult]
    warnings: List[str] = field(default_factory=list)


class IcpIntegrationService:
    """Best-effort integration helper for ICP-Brasil timestamping and PAdES signing."""

    def __init__(
        self,
        *,
        timestamp_url: str | None = None,
        timestamp_api_key: str | None = None,
        timestamp_username: str | None = None,
        timestamp_password: str | None = None,
        certificate_path: str | None = None,
        certificate_password: str | None = None,
        default_reason: str | None = None,
        default_location: str | None = None,
    ) -> None:
        self.timestamp_url = timestamp_url
        self.timestamp_api_key = timestamp_api_key
        self.timestamp_username = timestamp_username
        self.timestamp_password = timestamp_password
        self.certificate_path = Path(certificate_path) if certificate_path else None
        self.certificate_password = certificate_password
        self.default_reason = default_reason
        self.default_location = default_location

        self._signer = self._load_signer()

    @classmethod
    def from_settings(cls, settings) -> "IcpIntegrationService":  # type: ignore[no-untyped-def]
        return cls(
            timestamp_url=settings.icp_timestamp_url,
            timestamp_api_key=settings.icp_timestamp_api_key,
            timestamp_username=settings.icp_timestamp_username,
            timestamp_password=settings.icp_timestamp_password,
            certificate_path=settings.icp_certificate_path,
            certificate_password=settings.icp_certificate_password,
            default_reason=settings.icp_signature_reason,
            default_location=settings.icp_signature_location,
        )

    def _load_signer(self):  # type: ignore[no-untyped-def]
        if not signers or not self.certificate_path:
            return None
        if not self.certificate_path.exists():
            return None
        password_bytes = self.certificate_password.encode("utf-8") if self.certificate_password else None
        try:
            return signers.SimpleSigner.load_pkcs12_from_file(  # type: ignore[attr-defined]
                str(self.certificate_path),
                passphrase=password_bytes,
            )
        except Exception:  # pragma: no cover - invalid certificate configuration
            return None

    def _build_timestamper(self):  # type: ignore[no-untyped-def]
        if not HTTPTimeStamper or not self.timestamp_url:
            return None
        kwargs: dict[str, Any] = {}
        if self.timestamp_api_key:
            kwargs["extra_headers"] = {"Authorization": f"Bearer {self.timestamp_api_key}"}
        if self.timestamp_username and self.timestamp_password:
            kwargs["username"] = self.timestamp_username
            kwargs["password"] = self.timestamp_password
        try:
            return HTTPTimeStamper(self.timestamp_url, **kwargs)
        except Exception:  # pragma: no cover - misconfigured TSA endpoint
            return None

    def request_timestamp(self, payload: bytes) -> TimestampResult:
        """Request a timestamp token from the configured TSA or fallback locally."""

        digest = hashlib.sha256(payload).hexdigest()
        now = datetime.now(timezone.utc)

        if not self.timestamp_url:
            return TimestampResult(authority="local", issued_at=now, token=digest.encode("utf-8"))

        headers: dict[str, str] = {"content-type": "application/json"}
        if self.timestamp_api_key:
            headers["Authorization"] = f"Bearer {self.timestamp_api_key}"

        auth: tuple[str, str] | None = None
        if self.timestamp_username and self.timestamp_password:
            auth = (self.timestamp_username, self.timestamp_password)

        try:
            response = httpx.post(
                self.timestamp_url,
                json={"hash": digest, "hash_alg": "sha256"},
                headers=headers,
                auth=auth,
                timeout=10.0,
            )
            response.raise_for_status()
            payload_json = response.json()
        except Exception as exc:  # pragma: no cover - network/runtime issues
            return TimestampResult(
                authority=self.timestamp_url,
                issued_at=now,
                token=digest.encode("utf-8"),
                raw_response={"warning": f"timestamp-error:{exc}"},
            )

        token_b64 = payload_json.get("token") or payload_json.get("tsr") or payload_json.get("timestampToken")
        try:
            token = base64.b64decode(token_b64) if token_b64 else digest.encode("utf-8")
        except Exception:  # pragma: no cover - invalid payload
            token = digest.encode("utf-8")

        issued_at_raw = (
            payload_json.get("issued_at")
            or payload_json.get("timestamp")
            or payload_json.get("generated_at")
        )
        issued_at = now
        if isinstance(issued_at_raw, str):
            try:
                issued_at = datetime.fromisoformat(issued_at_raw)
                if issued_at.tzinfo is None:
                    issued_at = issued_at.replace(tzinfo=timezone.utc)
                else:
                    issued_at = issued_at.astimezone(timezone.utc)
            except ValueError:  # pragma: no cover - malformed payload
                issued_at = now

        authority = (
            payload_json.get("authority")
            or payload_json.get("tsa")
            or payload_json.get("provider")
            or self.timestamp_url
        )
        return TimestampResult(authority=authority, issued_at=issued_at, token=token, raw_response=payload_json)

    def sign_pdf(
        self,
        pdf_bytes: bytes,
        *,
        reason: str | None = None,
        location: str | None = None,
        timestamp: TimestampResult | None = None,
    ) -> SignatureResult:
        """Apply a PAdES signature when the certificate is configured."""

        warnings: list[str] = []
        effective_reason = reason or self.default_reason or "Assinado via NacionalSign"
        effective_location = location or self.default_location or "Brasil"

        if not self._signer or not PdfSigner or not PdfSignatureMetadata or not IncrementalPdfFileWriter:
            if not self._signer:
                warnings.append("signer-missing")
            else:
                warnings.append("pyhanko-missing")
            fallback_pdf = pdf_bytes
            if PdfWriter and PdfReader:
                try:
                    reader = PdfReader(io.BytesIO(pdf_bytes))  # type: ignore[arg-type]
                    writer = PdfWriter()  # type: ignore[call-arg]
                    for page in reader.pages:
                        writer.add_page(page)
                    metadata = {}
                    if reader.metadata:
                        metadata.update({k: str(v) for k, v in reader.metadata.items() if v is not None})
                    metadata["/Producer"] = "NacionalSign Fallback"
                    metadata["/NSDigest"] = hashlib.sha256(pdf_bytes).hexdigest()
                    if timestamp and timestamp.issued_at:
                        metadata["/NSIssuedAt"] = timestamp.issued_at.isoformat()
                    writer.add_metadata(metadata)
                    buffer = io.BytesIO()
                    writer.write(buffer)
                    fallback_pdf = buffer.getvalue()
                except Exception:  # pragma: no cover - fallback metadata injection failed
                    warnings.append("fallback-metadata-error")
            else:
                warnings.append("pypdf-missing")
            sha256 = hashlib.sha256(fallback_pdf).hexdigest()
            return SignatureResult(fallback_pdf, sha256, timestamp, warnings)

        buffer = io.BytesIO(pdf_bytes)
        try:
            writer = IncrementalPdfFileWriter(buffer)  # type: ignore[arg-type]
            metadata = PdfSignatureMetadata(field_name="NacionalSign", reason=effective_reason, location=effective_location)
            timestamper = self._build_timestamper() if timestamp or self.timestamp_url else None
            pdf_signer = PdfSigner(metadata, signer=self._signer, timestamper=timestamper)
            output = io.BytesIO()
            pdf_signer.sign_pdf(writer, output=output)
            signed_pdf = output.getvalue()
        except Exception as exc:  # pragma: no cover - signing failed
            warnings.append(f"sign-error:{exc}")
            signed_pdf = pdf_bytes

        sha256 = hashlib.sha256(signed_pdf).hexdigest()
        return SignatureResult(signed_pdf, sha256, timestamp, warnings)

    def apply_security(
        self,
        pdf_bytes: bytes,
        *,
        reason: str | None = None,
        location: str | None = None,
        request_timestamp: bool = True,
    ) -> SignatureResult:
        """Convenience helper that timestamps and signs the PDF when possible."""

        warnings: list[str] = []
        timestamp_result: TimestampResult | None = None
        if request_timestamp:
            try:
                timestamp_result = self.request_timestamp(pdf_bytes)
            except Exception as exc:  # pragma: no cover
                warnings.append(f"timestamp-error:{exc}")

        signature_result = self.sign_pdf(
            pdf_bytes,
            reason=reason,
            location=location,
            timestamp=timestamp_result,
        )
        signature_result.warnings.extend(warnings)
        if signature_result.timestamp is None:
            signature_result.timestamp = timestamp_result
        return signature_result



