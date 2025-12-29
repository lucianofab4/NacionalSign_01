from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable, List, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
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
        generated_at = datetime.utcnow()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=LETTER,
            leftMargin=0.8 * inch,
            rightMargin=0.8 * inch,
            topMargin=1 * inch,
            bottomMargin=0.75 * inch,
            pageCompression=0,
        )
        doc.title = f"Relatório {document.name}"

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Heading1"],
            alignment=1,
            fontSize=16,
            leading=19,
            textColor=colors.HexColor("#11284b"),
            spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["BodyText"],
            alignment=1,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#4f5d75"),
            spaceAfter=12,
        )
        section_style = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontSize=12,
            leading=14,
            textColor=colors.HexColor("#0f5298"),
            spaceBefore=14,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "ReportBody",
            parent=styles["BodyText"],
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#101820"),
        )
        muted_style = ParagraphStyle(
            "MutedBody",
            parent=body_style,
            fontSize=9,
            textColor=colors.HexColor("#5f6d7a"),
        )

        def fmt_datetime(value: datetime | None) -> str:
            if not value:
                return "-"
            return value.strftime("%d/%m/%Y %H:%M:%S UTC")

        def fmt_value(value: object | None) -> str:
            if value is None or value == "":
                return "-"
            return str(value)

        def lines_to_html(lines: list[str | tuple[str, bool]] | str) -> str:
            if isinstance(lines, str):
                return escape(lines) if lines else "-"
            html_parts: list[str] = []
            for entry in lines:
                text = entry
                bold = False
                if isinstance(entry, tuple):
                    text, bold = entry
                if text in (None, ""):
                    continue
                safe = escape(str(text))
                html_parts.append(f"<b>{safe}</b>" if bold else safe)
            if not html_parts:
                html_parts.append("-")
            return "<br/>".join(html_parts)

        def lines_to_paragraph(lines: list[str | tuple[str, bool]] | str, style: ParagraphStyle = body_style) -> Paragraph:
            return Paragraph(lines_to_html(lines), style)

        def apply_table_style(table: Table) -> Table:
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce4f2")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#102a43")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                        ("TOPPADDING", (0, 0), (-1, 0), 6),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8d1e4")),
                    ]
                )
            )
            return table

        story: list = []
        story.append(Paragraph("Relatório de auditoria", title_style))
        subtitle = f"Documento {escape(fmt_value(document.name))} · ID {escape(fmt_value(document.id))}"
        story.append(Paragraph(subtitle, subtitle_style))
        story.append(lines_to_paragraph("Todos os horários listados estão no fuso UTC.", muted_style))
        story.append(Spacer(1, 14))

        metadata = [
            ("Documento ID", fmt_value(document.id)),
            ("Status final", fmt_value(getattr(document.status, "value", document.status))),
            ("Workflow ID", fmt_value(workflow.id)),
            ("Gerado em", fmt_datetime(generated_at)),
        ]
        metadata_table = Table(
            [
                [Paragraph(f"<b>{escape(label)}</b>", body_style), Paragraph(escape(value), body_style)]
                for label, value in metadata
            ],
            colWidths=[doc.width * 0.35, doc.width * 0.65],
            hAlign="LEFT",
        )
        metadata_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d6dbe7")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b7c2d7")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(metadata_table)
        story.append(Spacer(1, 10))

        parties = list(self._gather_parties(document))
        story.append(Paragraph("Participantes", section_style))
        if parties:
            party_rows = [
                [
                    Paragraph("<b>Participante</b>", body_style),
                    Paragraph("<b>Contato</b>", body_style),
                    Paragraph("<b>Status</b>", body_style),
                ]
            ]
            for party in parties:
                contact_lines: list[str] = []
                if party.email:
                    contact_lines.append(f"Email: {party.email}")
                if party.phone_number:
                    contact_lines.append(f"Telefone: {party.phone_number}")
                contact_lines.append(f"Função: {fmt_value(party.role)}")
                status_value = getattr(party.status, "value", party.status)
                party_rows.append(
                    [
                        lines_to_paragraph([(fmt_value(party.full_name), True)]),
                        lines_to_paragraph(contact_lines),
                        lines_to_paragraph([fmt_value(status_value)]),
                    ]
                )
            party_table = Table(
                party_rows,
                colWidths=[doc.width * 0.35, doc.width * 0.4, doc.width * 0.25],
                hAlign="LEFT",
                repeatRows=1,
            )
            story.append(apply_table_style(party_table))
        else:
            story.append(lines_to_paragraph(["Nenhum participante registrado."], muted_style))
        story.append(Spacer(1, 6))

        requests = list(self._gather_requests(workflow))
        story.append(Paragraph("Solicitações", section_style))
        if requests:
            request_rows = [
                [
                    Paragraph("<b>Solicitação</b>", body_style),
                    Paragraph("<b>Detalhes</b>", body_style),
                    Paragraph("<b>Assinaturas</b>", body_style),
                ]
            ]
            for request in requests:
                step = self.session.get(WorkflowStep, request.workflow_step_id)
                party = step.party if step else None
                details_lines: list[str | tuple[str, bool]] = [
                    (f"Parte: {fmt_value(party.full_name if party else '-')}", True),
                    f"Status: {fmt_value(getattr(request.status, 'value', request.status))}",
                    f"Canal: {fmt_value(request.token_channel)}",
                    f"Emitido em: {fmt_datetime(request.created_at)}",
                ]
                signature_blocks: list[str] = []
                for signature in request.signature or []:
                    block_lines: list[str | tuple[str, bool]] = [
                        (f"Ação: {fmt_value(signature.reason) or 'assinatura'}", True),
                        f"Data: {fmt_datetime(getattr(signature, 'signed_at', None))}",
                        f"IP: {fmt_value(signature.signer_ip)}",
                    ]
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
                        evidence_lines.append("Modalidades: " + ", ".join(modes))
                    if signature.typed_name:
                        evidence_lines.append(f"Nome digitado: {signature.typed_name}")
                        if signature.typed_name_hash:
                            evidence_lines.append(f"Hash do nome: {signature.typed_name_hash}")
                    artifact = None
                    if signature.evidence_image_artifact_id:
                        artifact = self.session.get(AuditArtifact, signature.evidence_image_artifact_id)
                    if artifact:
                        evidence_lines.append(f"Imagem em: {artifact.storage_path}")
                        evidence_lines.append(f"Hash da imagem: {artifact.sha256}")
                        mime = signature.evidence_image_mime_type or "desconhecido"
                        size_display = f"{signature.evidence_image_size or 0} bytes"
                        evidence_lines.append(f"Detalhe: {mime} ({size_display})")
                    if signature.consent_given:
                        consent_line = "Consentimento LGPD: concedido"
                        if signature.consent_version:
                            consent_line += f" (versão {signature.consent_version})"
                        evidence_lines.append(consent_line)
                        if signature.consent_given_at:
                            evidence_lines.append(f"Registrado em: {fmt_datetime(signature.consent_given_at)}")
                    if evidence_lines:
                        block_lines.append("")
                        block_lines.append(("Dados fornecidos:", True))
                        block_lines.extend(evidence_lines)
                    signature_blocks.append(lines_to_html(block_lines))
                signatures_cell = Paragraph("-", body_style)
                if signature_blocks:
                    signatures_cell = Paragraph("<br/><br/>".join(signature_blocks), body_style)
                request_rows.append(
                    [
                        lines_to_paragraph([f"Solicitação {request.id}", f"Etapa: {fmt_value(getattr(step, 'step_index', '-'))}"]),
                        lines_to_paragraph(details_lines),
                        signatures_cell,
                    ]
                )
            request_table = Table(
                request_rows,
                colWidths=[doc.width * 0.22, doc.width * 0.35, doc.width * 0.43],
                hAlign="LEFT",
                repeatRows=1,
            )
            story.append(apply_table_style(request_table))
        else:
            story.append(lines_to_paragraph(["Nenhuma solicitação registrada."], muted_style))
        story.append(Spacer(1, 6))

        logs = list(self._gather_logs(document))
        story.append(Paragraph("Eventos de auditoria", section_style))
        if logs:
            log_rows = [
                [
                    Paragraph("<b>Horário</b>", body_style),
                    Paragraph("<b>Evento</b>", body_style),
                    Paragraph("<b>Detalhes</b>", body_style),
                ]
            ]
            for log in logs:
                detail_text = json.dumps(log.details or {}, ensure_ascii=False, indent=2)
                detail_html = escape(detail_text).replace("\n", "<br/>").replace("  ", "&nbsp;&nbsp;")
                log_rows.append(
                    [
                        lines_to_paragraph([fmt_datetime(log.created_at)]),
                        lines_to_paragraph([log.event_type]),
                        Paragraph(detail_html, body_style),
                    ]
                )
            log_table = Table(
                log_rows,
                colWidths=[doc.width * 0.25, doc.width * 0.2, doc.width * 0.55],
                hAlign="LEFT",
                repeatRows=1,
            )
            story.append(apply_table_style(log_table))
        else:
            story.append(lines_to_paragraph(["Nenhum evento de auditoria disponível."], muted_style))

        story.append(Spacer(1, 12))

        def draw_header_footer(pdf_canvas, doc_template) -> None:
            pdf_canvas.saveState()
            header_y = LETTER[1] - 0.65 * inch
            footer_y = 0.6 * inch
            pdf_canvas.setFillColor(colors.HexColor("#102a43"))
            pdf_canvas.setFont("Helvetica-Bold", 10)
            pdf_canvas.drawString(doc_template.leftMargin, header_y, "NacionalSign · Relatório de auditoria")
            pdf_canvas.setFont("Helvetica", 8)
            pdf_canvas.setFillColor(colors.HexColor("#5c677d"))
            pdf_canvas.drawRightString(
                LETTER[0] - doc_template.rightMargin,
                header_y,
                f"Documento {document.id}",
            )
            pdf_canvas.drawString(
                doc_template.leftMargin,
                footer_y,
                f"Gerado em {fmt_datetime(generated_at)}",
            )
            pdf_canvas.drawRightString(
                LETTER[0] - doc_template.rightMargin,
                footer_y,
                f"Página {pdf_canvas.getPageNumber()}",
            )
            pdf_canvas.restoreState()

        doc.build(story, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
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
