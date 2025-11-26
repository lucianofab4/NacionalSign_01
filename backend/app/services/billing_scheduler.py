from datetime import datetime
from sqlmodel import Session, select
from app.models.billing import Invoice
from app.services.billing import BillingService
from app.core.config import settings

# Rotina simples para reprocessar faturas pendentes/processing com next_attempt_at vencido

def run_billing_scheduler(session: Session):
    now = datetime.utcnow()
    invoices = session.exec(
        select(Invoice)
        .where((Invoice.status != "paid") & (Invoice.status != "failed") & (Invoice.next_attempt_at != None) & (Invoice.next_attempt_at <= now))
    ).all()
    service = BillingService(session)
    for invoice in invoices:
        try:
            service.retry_invoice(tenant_id=invoice.tenant_id, invoice_id=invoice.id)
            print(f"Fatura {invoice.id} reprocessada.")
        except Exception as e:
            print(f"Erro ao reprocessar fatura {invoice.id}: {e}")
