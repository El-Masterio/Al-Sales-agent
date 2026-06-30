"""
app/services/dashboard_service.py
=================================
Dashboard overview, time-series, pipeline, and report generation.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.reply_repository import ReplyRepository
from app.repositories.stats_repository import StatsRepository
from app.schemas.dashboard import (
    DailyStatPoint,
    DashboardOverview,
    DashboardTimeSeries,
    PipelineStage,
    PipelineSummary,
    ReportResponse,
)


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stats = StatsRepository(session)
        self.replies = ReplyRepository(session)

    async def get_overview(self) -> DashboardOverview:
        counts = await self.stats.get_overview_counts()
        return DashboardOverview(**counts)

    async def get_time_series(
        self, start: date, end: date, campaign_id: uuid.UUID | None = None
    ) -> DashboardTimeSeries:
        rows = await self.stats.get_range(start, end, campaign_id)
        points = [
            DailyStatPoint(
                date=r.stat_date,
                leads_added=r.leads_added,
                emails_sent=r.emails_sent,
                emails_opened=r.emails_opened,
                replies_received=r.replies_received,
                meetings_booked=r.meetings_booked,
                revenue_usd=r.revenue_usd,
            )
            for r in rows
        ]
        return DashboardTimeSeries(points=points)

    async def get_pipeline(self) -> PipelineSummary:
        stage_data = await self.stats.get_pipeline_value_by_stage()
        stages = [PipelineStage(status=s["status"], count=s["count"]) for s in stage_data]
        return PipelineSummary(stages=stages, total_value_usd=0)

    async def generate_report(
        self, start: date, end: date, campaign_id: uuid.UUID | None = None
    ) -> ReportResponse:
        overview = await self.get_overview()
        time_series = await self.get_time_series(start, end, campaign_id)
        reply_breakdown = await self.replies.get_classification_breakdown()

        return ReportResponse(
            period_start=start,
            period_end=end,
            summary=overview,
            time_series=time_series,
            top_performing_campaigns=[],
            reply_breakdown=reply_breakdown,
        )
