from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sqlalchemy import JSON
except ImportError:
    from sqlalchemy import Text as JSON  # type: ignore

from app.db.base import Base


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    messages: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now()
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
