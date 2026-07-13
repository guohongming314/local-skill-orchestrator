from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class Run(TimestampMixin, Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    repository_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    checkpoint_namespace: Mapped[str | None] = mapped_column(String(255))
    resume_input_digest: Mapped[str | None] = mapped_column(String(128))
    permission_state_digest: Mapped[str | None] = mapped_column(String(128))
    error_summary: Mapped[str | None] = mapped_column(Text)


class CodexThread(TimestampMixin, Base):
    __tablename__ = "codex_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    codex_thread_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)


class InventoryCache(Base):
    __tablename__ = "inventory_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_digest: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    inventory_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CapabilityVerification(Base):
    __tablename__ = "capability_verifications"
    __table_args__ = (
        Index(
            "ix_capability_verifications_identity",
            "capability_id",
            "content_digest",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )


class UserTrustDecision(Base):
    __tablename__ = "user_trust_decisions"
    __table_args__ = (
        Index(
            "ix_user_trust_decisions_identity",
            "capability_id",
            "content_digest",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_json: Mapped[str] = mapped_column(Text, nullable=False)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
