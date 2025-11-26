"""
Revision ID: ed1b196b6e28
Revises: 6bb4c3202f7d
Create Date: 2025-11-07 15:12:21.714521

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ed1b196b6e28'
down_revision = '6bb4c3202f7d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("workflow_steps")}

    if "phase_index" not in columns:
        op.add_column(
            "workflow_steps",
            sa.Column("phase_index", sa.Integer(), nullable=True),
        )

    op.execute(sa.text("UPDATE workflow_steps SET phase_index = step_index WHERE phase_index IS NULL"))
    op.alter_column(
        "workflow_steps",
        "phase_index",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("1"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("workflow_steps")}
    if "phase_index" in columns:
        op.drop_column("workflow_steps", "phase_index")
