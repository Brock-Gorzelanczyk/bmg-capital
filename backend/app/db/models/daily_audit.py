"""ORM model for daily_audit_log table (m050)."""
from __future__ import annotations

from sqlalchemy import Column, Integer, Text

from app.db.base import Base


class DailyAuditLog(Base):
    __tablename__ = "daily_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_at = Column(Text, nullable=False)
    overall_status = Column(Text, nullable=False)
    checks_json = Column(Text, nullable=False)
    alerts_json = Column(Text, nullable=False)
    summary_markdown = Column(Text, nullable=False)
