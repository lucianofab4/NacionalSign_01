from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from sqlmodel import Session, select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.document import AuditArtifact, Document, DocumentParty
from app.models.workflow import SignatureRequest, WorkflowInstance, WorkflowStep
from app.services.icp import IcpIntegrationService
from app.services.storage import LocalStorage, get_storage, normalize_storage_path, resolve_storage_root

BASE_STORAGE = resolve_storage_root()

class ReportService:
    def __init__(self, session: Session, icp_service: IcpIntegrationService | None = None) -> None:
        self.session = session
        self.icp_service = icp_service or IcpIntegrationService.from_settings(settings)

    def _get_storage_backend(self) -> LocalStorage | any:
        storage = get_storage()
        override_base = BASE_STORAGE
        if override_base and isinstance(storage, LocalStorage):
            try:
                override_path = Path(override_base)
            except Exception:
                override_path = Path(str(override_base))

            current_base = getattr(storage, "base_dir", None)
            try:
                current_base_path = Path(current_base) if current_base else None
            except Exception:
                current_base_path = None

            if current_base_path != override_path:
                storage = LocalStorage(base_dir=override_path)
        return storage

    def _gather_parties(self, document: Document) -> Iterable[DocumentParty]:
        return self.session.exec(
            select(DocumentParty)
            .where(DocumentParty.document_id == document.id)
            .order_by(DocumentParty.order_index)
        ).all()

    def _gather_requests(self, workflow: WorkflowInstance) -> Iterable[SignatureRequest]:
        return self.session.exec(
            select(SignatureRequest)
            .join(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow.id)
            .order_by(WorkflowStep.step_index)
        ).all()

    def _gather_logs(self, document: Document) -> Iterable[AuditLog]:
        return self.session.exec(
            select(AuditLog)
            .where(AuditLog.document_id == document.id)
            .order_by(AuditLog.created_at)
        ).all()

    def _build_pdf(self, document: Document, workflow: WorkflowInstance) -> bytes:
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=LETTER)
        pdf.setPageCompression(0)
        width, height = LETTER

        def write_lines(lines: List[str], start_y: float) -> float:
            y = start_y
            for line in lines:
                if y < 72:  # start a new page if the cursor is too low
                    pdf.showPage()
                    y = height - 72
                pdf.drawString(72, y, line)
                y -= 14
            return y

        pdf.setTitle(f"Relatório {document.name}")
        y = height - 72
        y = write_lines(
            [
                f"Relatório de auditoria - Documento {document.name}",
                f"Documento ID: {document.id}",
                f"Status final: {document.status.value}",
                f"Workflow ID: {workflow.id}",
                f"Gerado em: {datetime.utcnow():%d/%m/%Y %H:%M:%S UTC}",
                "",
            ],
            y,
        )

        y = write_lines(["Participantes:"], y)
        parties = self._gather_parties(document)
        for party in parties:
            y = write_lines(
                [
                    f"- {party.full_name} ({party.role})",
                    f"  Email: {party.email or '-'} | Telefone: {party.phone_number or '-'}",
                    f"  Status: {party.status}",
                    "",
                ],
                y,
            )

        y = write_lines(["Solicitações:"], y)
        requests = self._gather_requests(workflow)
        for request in requests:
            step = self.session.get(WorkflowStep, request.workflow_step_id)
            party = step.party if step else None
            y = write_lines(
                [
                    f"- Solicitação {request.id}",
                    f"  Parte: {party.full_name if party else '-'}",
                    f"  Status: {request.status.value}",
                    f"  Canal: {request.token_channel or '-'}",
                    f"  Emitido em: {request.created_at:%d/%m/%Y %H:%M:%S UTC}",
                ],
                y,
            )
            signatures = request.signature
            for signature in signatures:
                y = write_lines(
                    [
                        f"    - Ação: {signature.reason or 'assinatura'}",
                        f"      Data: {signature.signed_at:%d/%m/%Y %H:%M:%S UTC if signature.signed_at else '-'}",
                        f"      IP: {signature.signer_ip or '-'}",
                    ],
                    y,
                )
                evidence_lines: list[str] = []
                options = signature.evidence_options or {}
                modes: list[str] = []
                if options.get("typed_name"):
                    modes.append("nome digitado")
                if options.get("signature_image"):
                    modes.append("imagem")
                if options.get("signature_draw"):
                    modes.append("desenho")
                if modes:
                    evidence_lines.append("      Modalidades utilizadas: " + ", ".join(modes))
                if signature.typed_name:
                    evidence_lines.append(f"      Nome digitado: {signature.typed_name}")
                    if signature.typed_name_hash:
                        evidence_lines.append(f"      Hash do nome (SHA-256): {signature.typed_name_hash}")
                artifact = None
                if signature.evidence_image_artifact_id:
                    artifact = self.session.get(AuditArtifact, signature.evidence_image_artifact_id)
                if artifact:
                    evidence_lines.append(f"      Imagem armazenada em: {artifact.storage_path}")
                    evidence_lines.append(f"      Hash da imagem: {artifact.sha256}")
                    mime = signature.evidence_image_mime_type or "desconhecido"
                    size_display = f"{signature.evidence_image_size or 0} bytes"
                    evidence_lines.append(f"      Detalhe da imagem: {mime} ({size_display})")
                if signature.consent_given:
                    consent_line = "      Consentimento LGPD: concedido"
                    if signature.consent_version:
                        consent_line += f" (versão {signature.consent_version})"
                    evidence_lines.append(consent_line)
                    if signature.consent_given_at:
                        evidence_lines.append(
                            "      Registrado em: {:%d/%m/%Y %H:%M:%S UTC}".format(signature.consent_given_at)
                        )
                if evidence_lines:
                    evidence_lines.insert(0, "      Dados fornecidos pelo signatário:")
                    y = write_lines(evidence_lines, y)
            y = write_lines([""], y)

        y = write_lines(["Eventos de auditoria:"], y)
        logs = self._gather_logs(document)
        for log in logs:
            detail = json.dumps(log.details or {}, ensure_ascii=False)
            y = write_lines(
                [
                    f"- {log.created_at:%d/%m/%Y %H:%M:%S UTC} - {log.event_type}",
                    f"  Detalhes: {detail}",
                    "",
                ],
                y,
            )

        pdf.save()
        buffer.seek(0)
        return buffer.getvalue()

    def _persist_warnings(self, document: Document, warnings: List[str]) -> None:
        if not warnings:
            return
        for warning in warnings:
            log_entry = AuditLog(
                document_id=document.id,
                event_type="icp_warning",
                details={"warning": warning},
            )
            self.session.add(log_entry)
        self.session.commit()

    def generate_final_report(self, document: Document, workflow: WorkflowInstance) -> Tuple[AuditArtifact, List[AuditArtifact]]:
        unsigned_pdf = self._build_pdf(document, workflow)

        signature = self.icp_service.apply_security(
            unsigned_pdf,
            reason=f"Relatório final do documento {document.name}",
            location=self.icp_service.default_location,
        )

        storage = self._get_storage_backend()
        base_dir = resolve_storage_root()
        root_path = Path("reports") / str(document.tenant_id) / str(document.id)
        (base_dir / root_path).mkdir(parents=True, exist_ok=True)
        root = root_path.as_posix()
        file_path_str = storage.save_bytes(
            root=root,
            name="relatorio-final.pdf",
            data=signature.signed_pdf,
        )
        file_path_str = normalize_storage_path(file_path_str)

        issued_at = signature.timestamp.issued_at.replace(tzinfo=None) if signature.timestamp else datetime.utcnow()

        main_artifact = AuditArtifact(
            document_id=document.id,
            artifact_type="final_report",
            storage_path=file_path_str,
            sha256=signature.sha256,
            issued_at=issued_at,
        )
        extra_artifacts: List[AuditArtifact] = []
        self.session.add(main_artifact)

        if signature.timestamp and signature.timestamp.token:
            token_path_str = storage.save_bytes(
                root=root,
                name="relatorio-final.tsr",
                data=signature.timestamp.token,
            )
            token_path_str = normalize_storage_path(token_path_str)
            timestamp_artifact = AuditArtifact(
                document_id=document.id,
                artifact_type="final_report_timestamp",
                storage_path=token_path_str,
                sha256=hashlib.sha256(signature.timestamp.token).hexdigest(),
                issued_at=issued_at,
            )
            self.session.add(timestamp_artifact)
            extra_artifacts.append(timestamp_artifact)

        self.session.commit()
        self.session.refresh(main_artifact)
        for extra in extra_artifacts:
            self.session.refresh(extra)

        if signature.warnings:
            self._persist_warnings(document, signature.warnings)

        return main_artifact, extra_artifacts
