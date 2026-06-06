from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiscordSignalPost(Base):
    """Tracks Discord message IDs for bot signal posts so we can reply with outcomes."""
    __tablename__ = "discord_signal_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bot_signals.id", ondelete="SET NULL"), nullable=True, index=True)
    channel_id: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    bot_name: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    outcome_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
