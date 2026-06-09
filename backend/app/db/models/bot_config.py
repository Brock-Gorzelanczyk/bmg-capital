"""Runtime bot configuration override models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BotConfigOverride(Base):
    """Per-bot runtime config overrides — wins over YAML defaults.

    Key format:
      "risk.deployment_target_pct"
      "confidence_threshold"
      "cooldown_minutes"
      "enabled"
      "paused"
    Value is JSON so it can store floats, ints, bools, lists.
    """
    __tablename__ = "bot_config_overrides"
    __table_args__ = (
        UniqueConstraint("bot_id", "key", name="uq_bot_config_overrides_bot_key"),
        Index("idx_bot_config_overrides_bot", "bot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class BotConfigAudit(Base):
    """Append-only audit trail for every config change."""
    __tablename__ = "bot_config_audit"
    __table_args__ = (
        Index("idx_bot_config_audit_bot", "bot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    changed_by: Mapped[str] = mapped_column(Text, nullable=False)
