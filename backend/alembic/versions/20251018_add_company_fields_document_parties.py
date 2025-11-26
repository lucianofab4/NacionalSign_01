"""add company and requirement fields to document parties

Revision ID: add_company_fields_document_parties
Revises: add_phone_number_users
Create Date: 2025-10-18
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_company_fields_document_parties"
down_revision = "add_phone_number_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_parties", sa.Column("company_name", sa.String(length=128), nullable=True))
    op.add_column("document_parties", sa.Column("company_tax_id", sa.String(length=32), nullable=True))
    op.add_column("document_parties", sa.Column("require_cpf", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("document_parties", sa.Column("require_email", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("document_parties", sa.Column("require_phone", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "document_parties", sa.Column("allow_typed_name", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "document_parties", sa.Column("allow_signature_image", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "document_parties", sa.Column("allow_signature_draw", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.alter_column("document_parties", "require_cpf", server_default=None)
    op.alter_column("document_parties", "require_email", server_default=None)
    op.alter_column("document_parties", "require_phone", server_default=None)
    op.alter_column("document_parties", "allow_typed_name", server_default=None)
    op.alter_column("document_parties", "allow_signature_image", server_default=None)
    op.alter_column("document_parties", "allow_signature_draw", server_default=None)


def downgrade() -> None:
    op.drop_column("document_parties", "allow_signature_draw")
    op.drop_column("document_parties", "allow_signature_image")
    op.drop_column("document_parties", "allow_typed_name")
    op.drop_column("document_parties", "require_phone")
    op.drop_column("document_parties", "require_email")
    op.drop_column("document_parties", "require_cpf")
    op.drop_column("document_parties", "company_tax_id")
    op.drop_column("document_parties", "company_name")
