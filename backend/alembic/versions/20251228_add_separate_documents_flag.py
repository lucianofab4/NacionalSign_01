"""Add separate_documents flag to document groups

Revision ID: add_separate_documents_flag
Revises: group_workflow_single_instance
Create Date: 2025-12-28
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_separate_documents_flag"
down_revision = "group_workflow_single_instance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_groups",
        sa.Column("separate_documents", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("document_groups", "separate_documents", server_default=None)


def downgrade() -> None:
    op.drop_column("document_groups", "separate_documents")
