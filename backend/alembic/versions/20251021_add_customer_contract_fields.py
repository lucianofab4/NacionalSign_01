"""add customer contract fields

Revision ID: add_customer_contract_fields
Revises: add_customers_table
Create Date: 2025-10-21
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_customer_contract_fields"
down_revision = "add_customers_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("contract_storage_path", sa.String(length=512), nullable=True))
    op.add_column("customers", sa.Column("contract_original_filename", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("contract_mime_type", sa.String(length=128), nullable=True))
    op.add_column("customers", sa.Column("contract_uploaded_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "contract_uploaded_at")
    op.drop_column("customers", "contract_mime_type")
    op.drop_column("customers", "contract_original_filename")
    op.drop_column("customers", "contract_storage_path")
