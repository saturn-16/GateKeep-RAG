"""add document repair flag"""

from alembic import op
import sqlalchemy as sa

revision = "0002_document_repair_flag"
down_revision = "0001_initial"


def upgrade() -> None:
    op.add_column("documents", sa.Column("repair_required", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("documents", "repair_required")