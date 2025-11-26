"""add phone number field to users

Revision ID: add_phone_number_users
Revises: invoices_next_attempt_tax_fields
Create Date: 2025-10-18
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_phone_number_users"
down_revision = "invoices_next_attempt_tax_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone_number", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "phone_number")
