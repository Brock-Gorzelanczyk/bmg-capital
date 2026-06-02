from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Investor(Base):
    __tablename__ = "investors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    firm: Mapped[str] = mapped_column(default="")
    role: Mapped[str] = mapped_column(default="")
    contact_email: Mapped[Optional[str]] = mapped_column(nullable=True)
    twitter_handle: Mapped[Optional[str]] = mapped_column(nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(nullable=True)
    intro_path: Mapped[str] = mapped_column(default="cold")  # cold|warm|referral
    status: Mapped[str] = mapped_column(default="not_contacted", index=True)
    # not_contacted|email_sent|reply_received|meeting_scheduled|met|following_up|committed|passed
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    next_action: Mapped[Optional[str]] = mapped_column(nullable=True)
    notes_md: Mapped[str] = mapped_column(default="")
    check_size_target: Mapped[Optional[str]] = mapped_column(nullable=True)
    stage_focus: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())


class ContentPost(Base):
    __tablename__ = "content_posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str]  # twitter|linkedin|tiktok|reels|shorts|substack
    content_type: Mapped[str]  # tweet|thread|video|newsletter
    title: Mapped[str] = mapped_column(default="")
    body_md: Mapped[str] = mapped_column(default="")
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="draft")  # draft|scheduled|posted|archived
    performance_data: Mapped[dict] = mapped_column(JSON, default=dict)
    compliance_checked: Mapped[bool] = mapped_column(default=False)
    compliance_issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class WaitlistSignup(Base):
    __tablename__ = "waitlist_signups"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    source: Mapped[str] = mapped_column(default="direct")  # twitter|tiktok|instagram|podcast|direct
    referral_code: Mapped[str] = mapped_column(unique=True, index=True)
    position_in_queue: Mapped[int] = mapped_column(default=0, index=True)
    referred_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("waitlist_signups.id"), nullable=True)
    referral_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), index=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(default="")
