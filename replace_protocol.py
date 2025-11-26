# -*- coding: utf-8 -*-
from pathlib import Path
import re
path = Path('backend/app/services/document.py')
text = path.read_text(encoding='utf-8')
pattern = r"    def _build_protocol_summary\(self, document: Document\) -> list\[str\]:\n(?:        .+\n)+?        return lines\n"
new_block = '''    def _build_protocol_summary(self, document: Document) -> list[str]:
        """
        Gera o conteúdo textual do protocolo de ações e assinaturas,
        incluindo todos os participantes com os dados de cadastro.
        """
        lines: list[str] = []
        margin = " " * 4

        lines.append("+" + "-" * 78 + "+")
        lines.append("|" + " PROTOCOLO DE AÇÕES E ASSINATURAS ".center(78) + "|")
        lines.append("+" + "-" * 78 + "+")
        lines.append("")
        lines.append(f"{margin}Documento.......: {document.name}")
        lines.append(f"{margin}Referência......: {document.id}")
        if document.created_at:
            lines.append(f"{margin}Criado em.......: {document.created_at:%d/%m/%Y às %H:%M}")
        if document.updated_at:
            lines.append(f"{margin}Concluído em....: {document.updated_at:%d/%m/%Y às %H:%M}")
        lines.append("")

        parties = list(self.list_parties(document))
        if not parties:
            lines.append(f"{margin}Nenhum participante encontrado.")
            return lines

        signature_rows = self.session.exec(
            select(Signature, SignatureRequest, WorkflowStep, WorkflowInstance)
            .join(SignatureRequest, Signature.signature_request_id == SignatureRequest.id)
            .join(WorkflowStep, SignatureRequest.workflow_step_id == WorkflowStep.id)
            .join(WorkflowInstance, WorkflowStep.workflow_id == WorkflowInstance.id)
            .where(WorkflowInstance.document_id == document.id)
        ).all()

        signed_info: dict[UUID, dict[str, Any]] = {}

        def _guess_method(sig: Signature) -> str:
            if getattr(sig, "certificate_serial", None):
                return "digital (ICP-Brasil)"
            label = str(getattr(sig, "signature_type", "") or "").lower()
            if "digital" in label:
                return "digital (ICP-Brasil)"
            evidence = getattr(sig, "evidence_options", {}) or {}
            if evidence.get("certificate"):
                return "digital (ICP-Brasil)"
            return "eletrônica"

        for sig, _req, step, _wf in signature_rows:
            if not step.party_id:
                continue
            signed_info[step.party_id] = {
                "signed_at": sig.signed_at,
                "method": _guess_method(sig),
                "ip": sig.signer_ip,
            }

        for party in parties:
            if party.id not in signed_info and getattr(party, "signed_at", None):
                signed_info[party.id] = {
                    "signed_at": getattr(party, "signed_at"),
                    "method": "eletrônica",
                    "ip": getattr(party, "signer_ip", None),
                }

        lines.append("PARTICIPANTES E ASSINATURAS")
        lines.append("-" * 80)

        def _format_cnpj(value: str | None) -> str | None:
            if not value:
                return value
            digits = "".join(ch for ch in value if ch.isdigit())
            if len(digits) != 14:
                return value
            return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

        def _format_cpf(value: str | None) -> str | None:
            if not value:
                return value
            digits = "".join(ch for ch in value if ch.isdigit())
            if len(digits) != 11:
                return value
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

        for idx, party in enumerate(sorted(parties, key=lambda p: p.order_index or 0), 1):
            info = signed_info.get(party.id)
            status_line = "PENDENTE DE ASSINATURA"

            if info:
                signed_at = info.get("signed_at")
                dt = signed_at.strftime("%d/%m/%Y às %H:%M") if signed_at else "?"
                method = info.get("method") or "-"
                ip = f" | IP: {info['ip']}" if info.get("ip") else ""
                status_line = f"ASSINADO em {dt} via {method}{ip}"

            lines.append(f"{margin}{idx:2}. {party.full_name or 'Nome não informado'}")
            if party.role:
                lines.append(f"{margin}    Papel..........: {party.role}")
            if party.company_name:
                lines.append(f"{margin}    Empresa........: {party.company_name}")
            if party.company_tax_id:
                cnpj_fmt = _format_cnpj(party.company_tax_id)
                lines.append(f"{margin}    CNPJ...........: {cnpj_fmt or party.company_tax_id}")
            if party.cpf:
                cpf_fmt = _format_cpf(party.cpf)
                lines.append(f"{margin}    CPF............: {cpf_fmt or party.cpf}")
            if party.email:
                lines.append(f"{margin}    E-mail.........: {party.email}")
            lines.append(f"{margin}    Status.........: {status_line}")
            lines.append("")

        audit_logs = self.session.exec(
            select(AuditLog)
            .where(AuditLog.document_id == document.id)
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        ).all()
        if audit_logs:
            lines.append("ÚLTIMAS AÇÕES NO DOCUMENTO")
            lines.append("-" * 80)
            for log in reversed(audit_logs):
                dt = log.created_at.strftime("%d/%m %H:%M") if log.created_at else "?"
                event = (log.event_type or "ação desconhecida").replace("_", " ").title()
                user = getattr(log, "actor_name", None) or getattr(log, "actor_email", None) or "Sistema"
                lines.append(f"{margin}{dt} - {event} por {user}")

        lines.append("")
        lines.append("Este protocolo é parte integrante do documento e possui validade jurídica.")
        lines.append(f"Gerado pelo NacionalSign em {datetime.utcnow():%d/%m/%Y às %H:%M}")
        return lines
'''
new_text, count = re.subn(pattern, new_block, text, flags=re.S)
if count != 1:
    raise SystemExit('pattern not found or replaced multiple times')
path.write_text(new_text, encoding='utf-8')
