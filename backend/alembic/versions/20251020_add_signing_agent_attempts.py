"""add signing agent attempts table

Revision ID: add_signing_agent_attempts
Revises: add_signature_evidence_fields
Create Date: 2025-10-20
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_signing_agent_attempts"
down_revision = "add_signature_evidence_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signing_agent_attempts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("protocol", sa.String(length=128), nullable=True),
        sa.Column("agent_details", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_signing_agent_attempts_document_id",
        "signing_agent_attempts",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_signing_agent_attempts_version_id",
        "signing_agent_attempts",
        ["version_id"],
        unique=False,
    )
    op.create_index(
        "ix_signing_agent_attempts_actor_id",
        "signing_agent_attempts",
        ["actor_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_signing_agent_attempts_actor_id", table_name="signing_agent_attempts")
    op.drop_index("ix_signing_agent_attempts_version_id", table_name="signing_agent_attempts")
    op.drop_index("ix_signing_agent_attempts_document_id", table_name="signing_agent_attempts")
    op.drop_table("signing_agent_attempts")

