"""Create the initial business persistence schema."""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> tuple[sa.Column[Any], sa.Column[Any]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("repository_digest", sa.String(length=128), nullable=False),
        sa.Column("checkpoint_namespace", sa.String(length=255)),
        sa.Column("resume_input_digest", sa.String(length=128)),
        sa.Column("permission_state_digest", sa.String(length=128)),
        sa.Column("error_summary", sa.Text()),
        *timestamps(),
    )
    op.create_table(
        "codex_threads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("codex_thread_id", sa.String(length=255), nullable=False, unique=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "inventory_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_digest", sa.String(length=128), nullable=False, unique=True),
        sa.Column("inventory_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "capability_verifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("content_digest", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_capability_verifications_identity",
        "capability_verifications",
        ["capability_id", "content_digest"],
        unique=True,
    )
    op.create_table(
        "user_trust_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("content_digest", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("permissions_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_trust_decisions_identity",
        "user_trust_decisions",
        ["capability_id", "content_digest"],
        unique=True,
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64)),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_json", sa.Text(), nullable=False),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_index("ix_user_trust_decisions_identity", table_name="user_trust_decisions")
    op.drop_table("user_trust_decisions")
    op.drop_index("ix_capability_verifications_identity", table_name="capability_verifications")
    op.drop_table("capability_verifications")
    op.drop_table("inventory_cache")
    op.drop_table("codex_threads")
    op.drop_table("runs")
