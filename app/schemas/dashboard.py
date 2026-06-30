"""
app/schemas/dashboard.py
========================
Dashboard summary and reporting response schemas.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel


class DashboardOverview(BaseModel):
    total_leads: int
    new_leads_today: int
    emails_sent_today: int
    emails_sent_total: int
    open_rate_pct: float
    reply_rate_pct: float
    meetings_booked_today: int
    meetings_booked_total: int
    revenue_pipeline_usd: int
    active_campaigns: int


class DailyStatPoint(BaseModel):
    date: date
    leads_added: int
    emails_sent: int
    emails_opened: int
    replies_received: int
    meetings_booked: int
    revenue_usd: int


class DashboardTimeSeries(BaseModel):
    points: list[DailyStatPoint]


class PipelineStage(BaseModel):
    status: str
    count: int
    value_usd: int = 0


class PipelineSummary(BaseModel):
    stages: list[PipelineStage]
    total_value_usd: int


class ReportRequest(BaseModel):
    start_date: date
    end_date: date
    campaign_id: uuid.UUID | None = None


class ReportResponse(BaseModel):
    period_start: date
    period_end: date
    summary: DashboardOverview
    time_series: DashboardTimeSeries
    top_performing_campaigns: list[dict]
    reply_breakdown: dict[str, int]
