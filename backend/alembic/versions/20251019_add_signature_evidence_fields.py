"""add signature evidence fields

Revision ID: add_signature_evidence_fields
Revises: add_company_fields_document_parties
Create Date: 2025-10-19
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_signature_evidence_fields"
down_revision = "add_company_fields_document_parties"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signatures", sa.Column("typed_name", sa.String(length=256), nullable=True))
    op.add_column("signatures", sa.Column("typed_name_hash", sa.String(length=128), nullable=True))
    op.add_column("signatures", sa.Column("evidence_options", sa.JSON(), nullable=True))
    op.add_column("signatures", sa.Column("consent_given", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("signatures", sa.Column("consent_text", sa.Text(), nullable=True))
    op.add_column("signatures", sa.Column("consent_version", sa.String(length=64), nullable=True))
    op.add_column("signatures", sa.Column("consent_given_at", sa.DateTime(), nullable=True))
    op.add_column(
        "signatures",
        sa.Column("evidence_image_artifact_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column("signatures", sa.Column("evidence_image_mime_type", sa.String(length=64), nullable=True))
    op.add_column("signatures", sa.Column("evidence_image_size", sa.Integer(), nullable=True))
    op.add_column("signatures", sa.Column("evidence_image_sha256", sa.String(length=128), nullable=True))
    op.add_column("signatures", sa.Column("evidence_image_filename", sa.String(length=256), nullable=True))

    op.create_index("ix_signatures_typed_name_hash", "signatures", ["typed_name_hash"], unique=False)
    op.create_index(
        "ix_signatures_evidence_image_artifact_id",
        "signatures",
        ["evidence_image_artifact_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_signatures_evidence_image_artifact_id",
        "signatures",
        "document_artifacts",
        ["evidence_image_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column("signatures", "consent_given", server_default=None)


def downgrade() -> None:
    op.alter_column("signatures", "consent_given", server_default=sa.false())

    op.drop_constraint("fk_signatures_evidence_image_artifact_id", "signatures", type_="foreignkey")
    op.drop_index("ix_signatures_evidence_image_artifact_id", table_name="signatures")
    op.drop_index("ix_signatures_typed_name_hash", table_name="signatures")

    op.drop_column("signatures", "evidence_image_filename")
    op.drop_column("signatures", "evidence_image_sha256")
    op.drop_column("signatures", "evidence_image_size")
    op.drop_column("signatures", "evidence_image_mime_type")
    op.drop_column("signatures", "evidence_image_artifact_id")
    op.drop_column("signatures", "consent_given_at")
    op.drop_column("signatures", "consent_version")
    op.drop_column("signatures", "consent_text")
    op.drop_column("signatures", "consent_given")
    op.drop_column("signatures", "evidence_options")
    op.drop_column("signatures", "typed_name_hash")
    op.drop_column("signatures", "typed_name")
