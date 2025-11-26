from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlmodel import SQLModel
from app.db.base import *  # noqa: F401,F403 ensure models are imported into SQLModel.metadata

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create all tables from SQLModel metadata (initial baseline)
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.drop_all(bind=bind)
