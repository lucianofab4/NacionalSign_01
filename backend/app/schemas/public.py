from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel


class VerificationWorkflow(BaseModel):
    workflow_id: UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    steps_total: int
    steps_completed: int


class VerificationSigner(BaseModel):
    party_id: UUID
    full_name: str
    email: str
    role: str | None
    action: str
    status: str
    signed_at: datetime | None
    completed_at: datetime | None
    reason: str | None


class VerificationRead(BaseModel):
    document_id: UUID
    name: str
    status: str
    hash: str | None
    version_id: UUID | None
    version_filename: str | None
    version_size: int | None
    download_url: str | None
    report_url: str | None
    updated_at: datetime | None
    workflows: List[VerificationWorkflow]
    signers: List[VerificationSigner]


class PublicSignatureRead(BaseModel):
    document_name: str
    signer_name: str
    status: str
    expires_at: datetime | None
    can_sign: bool
    reason: str | None = None
    requires_email_confirmation: bool = False
    requires_phone_confirmation: bool = False
    supports_certificate: bool = False
    requires_certificate: bool = False
    signature_method: str = "electronic"


class PublicSignatureMeta(BaseModel):
    document_id: UUID
    version_id: UUID | None
    document_name: str
    signer_name: str
    status: str
    requires_certificate: bool
    supports_certificate: bool
    can_sign: bool
    reason: str | None = None
    requires_email_confirmation: bool = False
    requires_phone_confirmation: bool = False
    preview_url: str | None = None
    download_url: str | None = None
    signature_method: str = "electronic"
    signer_tax_id: str | None = None
    typed_name_required: bool = False




class PublicCertificateSignPayload(BaseModel):
    certificate_subject: str | None = None
    certificate_issuer: str | None = None
    certificate_serial: str | None = None
    certificate_thumbprint: str | None = None
    signature_protocol: str | None = None
    typed_name: str | None = None
    confirm_email: str | None = None
    confirm_phone_last4: str | None = None

class PublicSignatureAction(BaseModel):
    action: str
    reason: str | None = None
    typed_name: str | None = None
    signature_image: str | None = None
    signature_image_mime: str | None = None
    signature_image_name: str | None = None
    consent: bool | None = None
    consent_text: str | None = None
    consent_version: str | None = None
    confirm_email: str | None = None
    confirm_phone_last4: str | None = None
    certificate_subject: str | None = None
    certificate_issuer: str | None = None
    certificate_serial: str | None = None
    certificate_thumbprint: str | None = None
    signature_protocol: str | None = None
    signature_type: str | None = None
    signature_authentication: str | None = None
    signed_pdf: str | None = None
    signed_pdf_name: str | None = None
    signed_pdf_mime: str | None = None
    signed_pdf_digest: str | None = None
