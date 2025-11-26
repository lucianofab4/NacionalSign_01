"""
Add next_attempt_at and tax/receipt placeholder fields to invoices.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'invoices_next_attempt_tax_fields'
down_revision = 'dunning_retry_fields_invoices'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table('invoices'):
        cols = {c['name'] for c in insp.get_columns('invoices')}
        if 'next_attempt_at' not in cols:
            op.add_column('invoices', sa.Column('next_attempt_at', sa.DateTime(), nullable=True))
        if 'tax_id' not in cols:
            op.add_column('invoices', sa.Column('tax_id', sa.String(length=255), nullable=True))
        if 'receipt_url' not in cols:
            op.add_column('invoices', sa.Column('receipt_url', sa.String(length=1024), nullable=True))
        if 'fiscal_note_number' not in cols:
            op.add_column('invoices', sa.Column('fiscal_note_number', sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table('invoices'):
        cols = {c['name'] for c in insp.get_columns('invoices')}
        for col in ['fiscal_note_number', 'receipt_url', 'tax_id', 'next_attempt_at']:
            if col in cols:
                op.drop_column('invoices', col)
