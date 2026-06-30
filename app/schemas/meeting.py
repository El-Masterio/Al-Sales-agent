"""
app/schemas/meeting.py
======================
Meeting and calendar availability request/response schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.base import MeetingStatus
from app.schemas.common import TimestampedSchema


class AvailabilitySlot(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AvailabilityRequest(BaseModel):
    rep_id: uuid.UUID
    duration_minutes: int = Field(default=30, ge=15, le=180)
    days_ahead: int = Field(default=7, ge=1, le=30)
    earliest_hour_local: int = Field(default=9, ge=0, le=23)
    latest_hour_local: int = Field(default=17, ge=0, le=23)


class AvailabilityResponse(BaseModel):
    rep_id: uuid.UUID
    timezone: str
    slots: list[AvailabilitySlot]


class MeetingBookRequest(BaseModel):
    company_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    reply_id: uuid.UUID | None = None
    assigned_rep_id: uuid.UUID
    title: str
    description: str | None = None
    starts_at: datetime
    duration_minutes: int = Field(default=30, ge=15, le=180)
    timezone: str = "UTC"
    location_type: str = "video"


class MeetingUpdateRequest(BaseModel):
    status: MeetingStatus | None = None
    starts_at: datetime | None = None
    duration_minutes: int | None = None
    outcome: str | None = None
    outcome_notes: str | None = None
    next_steps: str | None = None
    deal_value_usd: int | None = None


class MeetingResponse(TimestampedSchema):
    company_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    assigned_rep_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    status: MeetingStatus
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    timezone: str
    location_type: str
    meeting_url: str | None = None
    google_event_id: str | None = None
    outcome: str | None = None
    deal_value_usd: int | None = None
