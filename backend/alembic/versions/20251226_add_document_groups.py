"""add document groups table and document group relationship

Revision ID: add_document_groups
Revises: add_user_notifications_table
Create Date: 2025-12-26
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_document_groups"
down_revision = "add_user_notifications_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_groups",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("area_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("signature_flow_mode", sa.String(length=32), nullable=False, server_default="SEQUENTIAL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_document_groups_tenant"),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"], name="fk_document_groups_area"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_document_groups_owner"),
    )
    op.create_index("ix_document_groups_tenant", "document_groups", ["tenant_id"])
    op.create_index("ix_document_groups_area", "document_groups", ["area_id"])
    op.create_index("ix_document_groups_owner", "document_groups", ["owner_id"])

    op.add_column("documents", sa.Column("group_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_documents_group",
        source_table="documents",
        referent_table="document_groups",
        local_cols=["group_id"],
        remote_cols=["id"],
    )
    op.create_index("ix_documents_group_id", "documents", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_group_id", table_name="documents")
    op.drop_constraint("fk_documents_group", "documents", type_="foreignkey")
    op.drop_column("documents", "group_id")

    op.drop_index("ix_document_groups_owner", table_name="document_groups")
    op.drop_index("ix_document_groups_area", table_name="document_groups")
    op.drop_index("ix_document_groups_tenant", table_name="document_groups")
    op.drop_table("document_groups")
