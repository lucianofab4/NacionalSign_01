"""scope user unique constraints per tenant

Revision ID: 20260105_scope_user_unique
Revises: 20251228_add_separate_documents_flag
Create Date: 2026-01-05 12:45:00
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260105_scope_user_unique"
down_revision = "20251228_add_separate_documents_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_email")
        batch.create_unique_constraint("uq_users_tenant_email", ["tenant_id", "email"])
        batch.create_unique_constraint("uq_users_tenant_cpf", ["tenant_id", "cpf"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_tenant_email", type_="unique")
        batch.drop_constraint("uq_users_tenant_cpf", type_="unique")
        batch.create_index("ix_users_email", ["email"], unique=True)
