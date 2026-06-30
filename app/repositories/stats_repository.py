"""
app/repositories/stats_repository.py
====================================
DailyStats data access and dashboard aggregation queries.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign
from app.models.company import Company
from app.models.daily_stats import DailyStats
from app.models.email import Email
from app.models.meeting import Meeting
from app.models.base import LeadStatus, MeetingStatus
from app.models.reply import Reply
from app.repositories.base import BaseRepository


class StatsRepository(BaseRepository[DailyStats]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(DailyStats, session)

    async def get_or_create_for_date(
        self, stat_date: date, campaign_id: uuid.UUID | None = None
    ) -> DailyStats:
        stmt = select(DailyStats).where(
            DailyStats.stat_date == stat_date,
            DailyStats.campaign_id == campaign_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        return await self.create(stat_date=stat_date, campaign_id=campaign_id)

    async def get_range(
        self, start: date, end: date, campaign_id: uuid.UUID | None = None
    ) -> list[DailyStats]:
        stmt = (
            select(DailyStats)
            .where(DailyStats.stat_date >= start)
            .where(DailyStats.stat_date <= end)
            .where(DailyStats.campaign_id == campaign_id)
            .order_by(DailyStats.stat_date)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Live (non-cached) dashboard queries ───────────────────────────────────

    async def get_overview_counts(self) -> dict[str, int]:
        """Real-time counts for the dashboard overview cards."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        total_leads = (
            await self.session.execute(select(func.count()).select_from(Company))
        ).scalar_one()

        new_leads_today = (
            await self.session.execute(
                select(func.count()).select_from(Company).where(Company.created_at >= today_start)
            )
        ).scalar_one()

        emails_sent_today = (
            await self.session.execute(
                select(func.count())
                .select_from(Email)
                .where(Email.sent_at >= today_start)
            )
        ).scalar_one()

        emails_sent_total = (
            await self.session.execute(
                select(func.count()).select_from(Email).where(Email.sent_at.is_not(None))
            )
        ).scalar_one()

        emails_opened_total = (
            await self.session.execute(
                select(func.count()).select_from(Email).where(Email.opened_count > 0)
            )
        ).scalar_one()

        replies_total = (
            await self.session.execute(select(func.count()).select_from(Reply))
        ).scalar_one()

        meetings_today = (
            await self.session.execute(
                select(func.count())
                .select_from(Meeting)
                .where(Meeting.created_at >= today_start)
                .where(Meeting.status.in_([MeetingStatus.CONFIRMED, MeetingStatus.COMPLETED]))
            )
        ).scalar_one()

        meetings_total = (
            await self.session.execute(
                select(func.count())
                .select_from(Meeting)
                .where(Meeting.status.in_([MeetingStatus.CONFIRMED, MeetingStatus.COMPLETED]))
            )
        ).scalar_one()

        revenue_pipeline = (
            await self.session.execute(
                select(func.coalesce(func.sum(Meeting.deal_value_usd), 0))
            )
        ).scalar_one()

        active_campaigns = (
            await self.session.execute(
                select(func.count()).select_from(Campaign).where(Campaign.status == "active")
            )
        ).scalar_one()

        open_rate = round(emails_opened_total / emails_sent_total * 100, 1) if emails_sent_total else 0.0
        reply_rate = round(replies_total / emails_sent_total * 100, 1) if emails_sent_total else 0.0

        return {
            "total_leads": total_leads,
            "new_leads_today": new_leads_today,
            "emails_sent_today": emails_sent_today,
            "emails_sent_total": emails_sent_total,
            "open_rate_pct": open_rate,
            "reply_rate_pct": reply_rate,
            "meetings_booked_today": meetings_today,
            "meetings_booked_total": meetings_total,
            "revenue_pipeline_usd": int(revenue_pipeline),
            "active_campaigns": active_campaigns,
        }

    async def get_pipeline_value_by_stage(self) -> list[dict]:
        stmt = (
            select(Company.lead_status, func.count())
            .group_by(Company.lead_status)
        )
        result = await self.session.execute(stmt)
        return [{"status": status, "count": count} for status, count in result.all()]
