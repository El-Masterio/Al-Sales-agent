"""
app/schemas/campaign.py
=======================
Campaign request/response schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.base import CampaignStatus, LeadStatus
from app.schemas.company import ICPCriteria
from app.schemas.common import TimestampedSchema


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    icp_criteria: ICPCriteria = Field(default_factory=ICPCriteria)
    max_leads: int = Field(default=500, ge=1, le=10000)
    follow_up_days: list[int] = Field(default=[3, 7, 14])
    max_attempts: int = Field(default=4, ge=1, le=10)
    from_name: str
    from_email: EmailStr
    reply_to_email: EmailStr | None = None
    email_provider: str = "sendgrid"
    value_proposition: str | None = None
    tone: str = "professional"
    llm_model: str = "gpt-4.1"


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icp_criteria: ICPCriteria | None = None
    max_leads: int | None = None
    follow_up_days: list[int] | None = None
    max_attempts: int | None = None
    value_proposition: str | None = None
    tone: str | None = None
    status: CampaignStatus | None = None


class CampaignResponse(TimestampedSchema):
    name: str
    description: str | None = None
    owner_id: uuid.UUID
    icp_criteria: dict
    max_leads: int
    follow_up_days: list[int]
    max_attempts: int
    from_name: str
    from_email: str
    status: CampaignStatus
    stat_leads_added: int
    stat_emails_sent: int
    stat_emails_opened: int
    stat_replies: int
    stat_meetings: int
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CampaignStatsResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    total_leads: int
    leads_contacted: int
    leads_replied: int
    leads_engaged: int
    emails_sent: int
    emails_opened: int
    emails_clicked: int
    replies_total: int
    meetings_booked: int
    open_rate_pct: float
    reply_rate_pct: float


class CampaignLeadResponse(TimestampedSchema):
    campaign_id: uuid.UUID
    company_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    status: LeadStatus
    attempt_count: int
    next_follow_up: datetime | None = None
    stopped_at: datetime | None = None
    stop_reason: str | None = None


class AddLeadsToCampaignRequest(BaseModel):
    company_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
