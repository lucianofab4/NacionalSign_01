"""Add signature_method to document_parties

Revision ID: add_signature_method_to_parties
Revises: add_customer_contract_fields
Create Date: 2025-11-02 04:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_signature_method_to_parties"
down_revision = "add_customer_contract_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_parties",
        sa.Column("signature_method", sa.String(length=32), nullable=False, server_default=sa.text("'electronic'")),
    )
    op.execute(
        "UPDATE document_parties SET signature_method = 'digital' "
        "WHERE upper(status) = 'SIGNED' AND coalesce(signature_method, '') = ''"
    )
    op.alter_column(
        "document_parties",
        "signature_method",
        server_default=None,
        existing_type=sa.String(length=32),
    )


def downgrade() -> None:
    op.drop_column("document_parties", "signature_method")
