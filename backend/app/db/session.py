from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite only
    # Default pool (5+10) was being exhausted during peak: bot scans running
    # alongside dashboard polling could hit "QueuePool limit … timeout 30.00"
    # and 500 user requests. SQLite can serve concurrent reads cheaply; the
    # bottleneck is the writer lock, which doesn't scale with connection count
    # but also doesn't break with extras (writers just queue inside SQLite).
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,    # drop dead connections instead of handing them out
    pool_recycle=3600,     # rotate every hour so long-lived workers don't accumulate stale state
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
