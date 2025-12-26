"""add user notifications table

Revision ID: add_user_notifications_table
Revises: ed1b196b6e28
Create Date: 2025-12-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_user_notifications_table"
down_revision = "ed1b196b6e28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recipient_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("party_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_notifications_tenant"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_notifications_document"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], name="fk_notifications_recipient"),
        sa.ForeignKeyConstraint(["party_id"], ["document_parties.id"], name="fk_notifications_party"),
    )
    op.create_index("ix_user_notifications_recipient", "user_notifications", ["recipient_id"])
    op.create_index("ix_user_notifications_document", "user_notifications", ["document_id"])
    op.create_index("ix_user_notifications_read_at", "user_notifications", ["read_at"])


def downgrade() -> None:
    op.drop_index("ix_user_notifications_read_at", table_name="user_notifications")
    op.drop_index("ix_user_notifications_document", table_name="user_notifications")
    op.drop_index("ix_user_notifications_recipient", table_name="user_notifications")
    op.drop_table("user_notifications")
