"""
app/api/v1/router.py
====================
Aggregates all v1 sub-routers into a single APIRouter mounted under /api/v1.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    calendar,
    campaigns,
    companies,
    dashboard,
    emails,
    meetings,
    replies,
)

api_router = APIRouter()

# Authenticated resource routers
api_router.include_router(auth.router)
api_router.include_router(companies.router)
api_router.include_router(campaigns.router)
api_router.include_router(emails.router)
api_router.include_router(replies.router)
api_router.include_router(meetings.router)
api_router.include_router(calendar.router)
api_router.include_router(dashboard.router)

# Unauthenticated routers (tracking + webhooks)
api_router.include_router(emails.tracking_router)
api_router.include_router(replies.webhook_router)
