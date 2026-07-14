"""Add low-sensitivity task outcomes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("workflow", sa.String(length=32), nullable=False),
        sa.Column("capabilities_used_json", sa.Text(), nullable=False),
        sa.Column("verification_passed", sa.Boolean(), nullable=False),
        sa.Column("user_rework", sa.Boolean(), nullable=False),
        sa.Column("unused_recommendations_json", sa.Text(), nullable=False),
        sa.Column("audit_event_id", sa.Integer(), unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["audit_event_id"], ["audit_events.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("task_outcomes")
