from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List
from uuid import UUID

from sqlmodel import Session, select, func

from app.models.document import Document, DocumentParty, DocumentStatus
from app.models.workflow import (
    Signature,
    SignatureRequest,
    SignatureType,
    WorkflowInstance,
    WorkflowStep,
)
from app.models.tenant import Area
from app.models.user import User
from app.schemas.reporting import DocumentReportParty, DocumentReportResponse, DocumentReportRow


@dataclass
class DocumentReportFilters:
    start_date: datetime | None = None
    end_date: datetime | None = None
    status: DocumentStatus | None = None
    area_id: UUID | None = None
    signature_method: str | None = None
    search: str | None = None


class ReportingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_documents(
        self,
        tenant_id: UUID,
        filters: DocumentReportFilters,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> DocumentReportResponse:
        conditions = [Document.tenant_id == tenant_id]

        if filters.start_date:
            conditions.append(Document.created_at >= filters.start_date)
        if filters.end_date:
            conditions.append(Document.created_at <= filters.end_date)
        if filters.status:
            conditions.append(Document.status == filters.status)
        if filters.area_id:
            conditions.append(Document.area_id == filters.area_id)
        if filters.search:
            normalized = f"%{filters.search.strip().lower()}%"
            conditions.append(func.lower(Document.name).like(normalized))
        if filters.signature_method:
            method = filters.signature_method.strip().lower()
            method_query = (
                select(DocumentParty.document_id)
                .where(DocumentParty.signature_method.isnot(None))
                .where(func.lower(DocumentParty.signature_method).like(f"{method}%"))
            )
            conditions.append(Document.id.in_(method_query))

        total_stmt = select(func.count()).select_from(Document).where(*conditions)
        total = self.session.exec(total_stmt).one()

        summary_stmt = (
            select(Document.status, func.count())
            .where(*conditions)
            .group_by(Document.status)
        )
        status_summary = {
            (status.value if isinstance(status, DocumentStatus) else str(status)): count
            for status, count in self.session.exec(summary_stmt).all()
        }

        document_stmt = (
            select(Document, Area, User)
            .join(Area, Area.id == Document.area_id)
            .join(User, User.id == Document.created_by_id)
            .where(*conditions)
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        raw_rows = self.session.exec(document_stmt).all()
        if not raw_rows:
            return DocumentReportResponse(items=[], total=int(total or 0), status_summary=status_summary)

        documents: List[Document] = []
        areas: Dict[UUID, Area] = {}
        creators: Dict[UUID, User] = {}
        document_ids: List[UUID] = []
        for document, area, user in raw_rows:
            documents.append(document)
            areas[document.id] = area
            creators[document.id] = user
            document_ids.append(document.id)

        workflows = self._load_latest_workflows(document_ids)
        parties_map = self._load_parties_with_signatures(document_ids)

        items: List[DocumentReportRow] = []
        for document in documents:
            doc_parties = parties_map.get(document.id, [])
            signed_parties = sum(1 for party in doc_parties if party.signed_at)
            total_parties = len(doc_parties)
            pending_parties = max(total_parties - signed_parties, 0)

            signed_digital = sum(
                1
                for party in doc_parties
                if party.signed_at and (party.signature_type or party.signature_method or "").startswith("digital")
            )
            signed_electronic = sum(
                1
                for party in doc_parties
                if party.signed_at and (party.signature_type or party.signature_method or "").startswith("electronic")
            )

            workflow = workflows.get(document.id)
            creator = creators.get(document.id)
            area = areas.get(document.id)

            items.append(
                DocumentReportRow(
                    document_id=document.id,
                    name=document.name,
                    status=document.status,
                    area_id=document.area_id,
                    area_name=area.name if area else "",
                    created_at=document.created_at,
                    updated_at=document.updated_at,
                    created_by_id=document.created_by_id,
                    created_by_name=getattr(creator, "full_name", None),
                    created_by_email=getattr(creator, "email", None),
                    workflow_started_at=getattr(workflow, "started_at", None),
                    workflow_completed_at=getattr(workflow, "completed_at", None),
                    total_parties=total_parties,
                    signed_parties=signed_parties,
                    pending_parties=pending_parties,
                    signed_digital=signed_digital,
                    signed_electronic=signed_electronic,
                    parties=doc_parties,
                )
            )

        return DocumentReportResponse(
            items=items,
            total=int(total or 0),
            status_summary=status_summary,
        )

    def _load_latest_workflows(self, document_ids: Iterable[UUID]) -> Dict[UUID, WorkflowInstance]:
        if not document_ids:
            return {}
        workflow_stmt = (
            select(WorkflowInstance)
            .where(WorkflowInstance.document_id.in_(document_ids))
            .order_by(
                WorkflowInstance.document_id,
                WorkflowInstance.started_at.desc().nullslast(),
                WorkflowInstance.created_at.desc(),
            )
        )
        workflows: Dict[UUID, WorkflowInstance] = {}
        for workflow in self.session.exec(workflow_stmt):
            if workflow.document_id not in workflows:
                workflows[workflow.document_id] = workflow
        return workflows

    def _load_parties_with_signatures(self, document_ids: Iterable[UUID]) -> Dict[UUID, List[DocumentReportParty]]:
        party_stmt = (
            select(DocumentParty)
            .where(DocumentParty.document_id.in_(document_ids))
            .order_by(DocumentParty.document_id, DocumentParty.order_index)
        )
        parties = self.session.exec(party_stmt).all()
        if not parties:
            return {}

        party_ids = [party.id for party in parties]
        signature_map = self._load_signatures_for_parties(party_ids)

        result: Dict[UUID, List[DocumentReportParty]] = {}
        for party in parties:
            signature = signature_map.get(party.id)
            signature_type = None
            signed_at = None
            if signature:
                signature_type = signature.signature_type.value if isinstance(signature.signature_type, SignatureType) else signature.signature_type
                signed_at = signature.signed_at or signature.created_at

            method_label = (party.signature_method or "").strip().lower()
            requires_certificate = bool(
                (signature_type and signature_type.startswith("digital")) or method_label.startswith("digital")
            )

            report_party = DocumentReportParty(
                party_id=party.id,
                document_id=party.document_id,
                full_name=party.full_name,
                email=party.email,
                role=party.role,
                company_name=party.company_name,
                company_tax_id=party.company_tax_id,
                signature_method=party.signature_method,
                signature_type=signature_type,
                status=party.status,
                order_index=party.order_index,
                signed_at=signed_at,
                requires_certificate=requires_certificate,
            )
            result.setdefault(party.document_id, []).append(report_party)

        return result

    def _load_signatures_for_parties(self, party_ids: Iterable[UUID]) -> Dict[UUID, Signature]:
        if not party_ids:
            return {}

        signature_stmt = (
            select(Signature, WorkflowStep.party_id)
            .join(SignatureRequest, Signature.signature_request_id == SignatureRequest.id)
            .join(WorkflowStep, SignatureRequest.workflow_step_id == WorkflowStep.id)
            .where(WorkflowStep.party_id.in_(party_ids))
            .where(Signature.signed_at.isnot(None))
            .order_by(Signature.signed_at.desc(), Signature.created_at.desc())
        )
        signature_map: Dict[UUID, Signature] = {}
        for signature, party_id in self.session.exec(signature_stmt).all():
            if party_id not in signature_map:
                signature_map[party_id] = signature
        return signature_map
