"""
Revision ID: 6bb4c3202f7d
Revises: add_signature_method_to_parties
Create Date: 2025-11-07 12:18:43.848625

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6bb4c3202f7d'
down_revision = 'add_signature_method_to_parties'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("document_parties")}

    if "is_active" not in columns:
        op.add_column(
            "document_parties",
            sa.Column("is_active", sa.Boolean(), nullable=True),
        )

    op.execute(sa.text("UPDATE document_parties SET is_active = TRUE WHERE is_active IS NULL"))
    op.alter_column(
        "document_parties",
        "is_active",
        server_default=sa.true(),
        existing_type=sa.Boolean(),
        nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("document_parties")}

    if "is_active" in columns:
        op.drop_column("document_parties", "is_active")
