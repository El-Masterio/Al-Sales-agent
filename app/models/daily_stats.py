"""
app/models/daily_stats.py
=========================
DailyStats: pre-aggregated daily metrics for fast dashboard rendering.
Populated by a nightly Celery beat task (app.workers.tasks.aggregate_daily_stats).

WebhookLog: audit trail of all inbound webhooks (SendGrid, SES, Google).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, StrLen

if TYPE_CHECKING:
    from app.models.campaign import Campaign


class DailyStats(Base, BaseModel):
    """
    One row per (stat_date, campaign_id) pair. campaign_id=NULL means
    the row aggregates global stats across all campaigns for that day.
    """

    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint("stat_date", "campaign_id", name="uq_daily_stats_date_campaign"),
    )

    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )

    leads_added: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    leads_researched: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    emails_sent: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    emails_opened: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    emails_clicked: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    replies_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    meetings_booked: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    meetings_completed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    deals_closed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    revenue_usd: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    # ── Relationships ─────────────────────────────────────────────────────────
    campaign: Mapped[Campaign | None] = relationship("Campaign", lazy="select")

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def open_rate(self) -> float:
        if self.emails_sent == 0:
            return 0.0
        return round(self.emails_opened / self.emails_sent * 100, 1)

    @property
    def reply_rate(self) -> float:
        if self.emails_sent == 0:
            return 0.0
        return round(self.replies_received / self.emails_sent * 100, 1)

    def increment(self, field: str, by: int = 1) -> None:
        current = getattr(self, field, 0)
        setattr(self, field, current + by)


class WebhookLog(Base):
    """
    Audit log of every inbound webhook received from email/calendar providers.
    Used for debugging delivery issues and replaying failed processing.
    """

    __tablename__ = "webhook_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        default=uuid.uuid4,
    )
    source: Mapped[str] = mapped_column(String(StrLen.SHORT), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(StrLen.SHORT), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=datetime.utcnow,
        index=True,
    )

    def mark_processed(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.processed = True
        self.processed_at = _dt.now(_tz.utc)

    def mark_failed(self, error: str) -> None:
        self.error = error
