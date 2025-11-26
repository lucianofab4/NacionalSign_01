"""add customers table

Revision ID: add_customers_table
Revises: add_signing_agent_attempts
Create Date: 2025-10-21
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_customers_table"
down_revision = "add_signing_agent_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("corporate_name", sa.String(), nullable=False),
        sa.Column("trade_name", sa.String(), nullable=True),
        sa.Column("cnpj", sa.String(length=18), nullable=False),
        sa.Column("responsible_name", sa.String(), nullable=False),
        sa.Column("responsible_email", sa.String(), nullable=True),
        sa.Column("responsible_phone", sa.String(length=32), nullable=True),
        sa.Column("plan_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("document_quota", sa.Integer(), nullable=True),
        sa.Column("documents_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("activation_token", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cnpj", name="uq_customers_cnpj"),
    )
    op.create_index("ix_customers_corporate_name", "customers", ["corporate_name"], unique=False)
    op.create_index("ix_customers_activation_token", "customers", ["activation_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_customers_activation_token", table_name="customers")
    op.drop_index("ix_customers_corporate_name", table_name="customers")
    op.drop_table("customers")


