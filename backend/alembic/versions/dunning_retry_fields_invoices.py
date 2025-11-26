"""
Add retry fields to invoices for payment retries/dunning.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'dunning_retry_fields_invoices'
down_revision = 'c5a62b19a879'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table('invoices'):
        cols = {c['name'] for c in insp.get_columns('invoices')}
        if 'retry_count' not in cols:
            op.add_column('invoices', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
            op.alter_column('invoices', 'retry_count', server_default=None)
        if 'last_attempt_at' not in cols:
            op.add_column('invoices', sa.Column('last_attempt_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if insp.has_table('invoices'):
        cols = {c['name'] for c in insp.get_columns('invoices')}
        if 'last_attempt_at' in cols:
            op.drop_column('invoices', 'last_attempt_at')
        if 'retry_count' in cols:
            op.drop_column('invoices', 'retry_count')
