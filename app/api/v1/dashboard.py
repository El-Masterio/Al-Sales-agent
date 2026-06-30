"""
app/api/v1/dashboard.py
=======================
Dashboard and reporting endpoints.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.dashboard import (
    DashboardOverview,
    DashboardTimeSeries,
    PipelineSummary,
    ReportResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverview)
async def get_overview(db: DbSession, user: CurrentUser) -> DashboardOverview:
    service = DashboardService(db)
    return await service.get_overview()


@router.get("/time-series", response_model=DashboardTimeSeries)
async def get_time_series(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(30, ge=1, le=365),
    campaign_id: uuid.UUID | None = None,
) -> DashboardTimeSeries:
    service = DashboardService(db)
    end = date.today()
    start = end - timedelta(days=days)
    return await service.get_time_series(start, end, campaign_id)


@router.get("/pipeline", response_model=PipelineSummary)
async def get_pipeline(db: DbSession, user: CurrentUser) -> PipelineSummary:
    service = DashboardService(db)
    return await service.get_pipeline()


@router.get("/report", response_model=ReportResponse)
async def get_report(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(7, ge=1, le=90),
    campaign_id: uuid.UUID | None = None,
) -> ReportResponse:
    service = DashboardService(db)
    end = date.today()
    start = end - timedelta(days=days)
    return await service.generate_report(start, end, campaign_id)
