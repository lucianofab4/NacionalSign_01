"""add deleted_at field to documents

Revision ID: 20260107_add_document_deleted_at
Revises: 20260105_scope_user_unique  
Create Date: 2026-01-07 15:30:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260107_add_document_deleted_at"
down_revision = "20260105_scope_user_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_documents_deleted_at", ["deleted_at"])


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_deleted_at")
        batch.drop_column("deleted_at")