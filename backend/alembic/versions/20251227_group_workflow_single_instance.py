"""Add group aware workflow columns and document scoped signature requests

Revision ID: group_workflow_single_instance
Revises: add_document_groups
Create Date: 2025-12-27
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "group_workflow_single_instance"
down_revision = "add_document_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("group_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column(
        "workflows",
        sa.Column("is_group_workflow", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_workflows_group",
        source_table="workflows",
        referent_table="document_groups",
        local_cols=["group_id"],
        remote_cols=["id"],
    )
    op.create_index("ix_workflows_group_id", "workflows", ["group_id"])

    op.execute(
        sa.text(
            """
            UPDATE workflows AS wf
            SET group_id = doc.group_id
            FROM documents AS doc
            WHERE wf.document_id = doc.id
              AND doc.group_id IS NOT NULL
            """
        )
    )

    op.add_column("signature_requests", sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("signature_requests", sa.Column("group_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_signature_requests_document",
        source_table="signature_requests",
        referent_table="documents",
        local_cols=["document_id"],
        remote_cols=["id"],
    )
    op.create_foreign_key(
        "fk_signature_requests_group",
        source_table="signature_requests",
        referent_table="document_groups",
        local_cols=["group_id"],
        remote_cols=["id"],
    )
    op.create_index("ix_signature_requests_document_id", "signature_requests", ["document_id"])
    op.create_index("ix_signature_requests_group_id", "signature_requests", ["group_id"])

    op.execute(
        sa.text(
            """
            UPDATE signature_requests AS sr
            SET document_id = wf.document_id
            FROM workflow_steps AS ws
            JOIN workflows AS wf ON wf.id = ws.workflow_id
            WHERE sr.workflow_step_id = ws.id
              AND sr.document_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE signature_requests AS sr
            SET group_id = wf.group_id
            FROM workflow_steps AS ws
            JOIN workflows AS wf ON wf.id = ws.workflow_id
            WHERE sr.workflow_step_id = ws.id
              AND wf.group_id IS NOT NULL
            """
        )
    )

    op.alter_column(
        "signature_requests",
        "document_id",
        existing_type=sa.Uuid(as_uuid=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "signature_requests",
        "document_id",
        existing_type=sa.Uuid(as_uuid=True),
        nullable=True,
    )
    op.drop_index("ix_signature_requests_group_id", table_name="signature_requests")
    op.drop_index("ix_signature_requests_document_id", table_name="signature_requests")
    op.drop_constraint("fk_signature_requests_group", "signature_requests", type_="foreignkey")
    op.drop_constraint("fk_signature_requests_document", "signature_requests", type_="foreignkey")
    op.drop_column("signature_requests", "group_id")
    op.drop_column("signature_requests", "document_id")

    op.drop_index("ix_workflows_group_id", table_name="workflows")
    op.drop_constraint("fk_workflows_group", "workflows", type_="foreignkey")
    op.drop_column("workflows", "is_group_workflow")
    op.drop_column("workflows", "group_id")
