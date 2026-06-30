"""
app/schemas/email.py
====================
Email and Reply request/response schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.base import EmailStatus, EmailType, ReplyClassification
from app.schemas.common import TimestampedSchema


class EmailGenerateRequest(BaseModel):
    """Request to generate (but not send) a personalized email."""

    company_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    campaign_id: uuid.UUID
    email_type: EmailType = EmailType.INITIAL_OUTREACH
    thread_context: list[dict] = Field(default_factory=list)


class EmailGenerateResponse(BaseModel):
    subject: str
    body_html: str
    body_text: str
    ai_model: str
    prompt_tokens: int
    completion_tokens: int
    generation_ms: int


class EmailSendRequest(BaseModel):
    company_id: uuid.UUID
    contact_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    email_type: EmailType = EmailType.INITIAL_OUTREACH
    subject: str
    body_html: str
    body_text: str
    scheduled_at: datetime | None = None


class EmailResponse(TimestampedSchema):
    campaign_id: uuid.UUID | None = None
    company_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    email_type: EmailType
    subject: str
    to_email: str
    to_name: str | None = None
    status: EmailStatus
    opened_count: int
    clicked_count: int
    sent_at: datetime | None = None
    ai_model: str | None = None


class EmailDetailResponse(EmailResponse):
    body_html: str
    body_text: str
    thread_id: str | None = None
    first_opened_at: datetime | None = None
    last_opened_at: datetime | None = None
    bounced_at: datetime | None = None
    bounce_reason: str | None = None


class InboundEmailWebhook(BaseModel):
    """Normalized inbound email payload (mapped from SendGrid/SES webhook format)."""

    from_email: EmailStr
    from_name: str | None = None
    to_email: EmailStr
    subject: str | None = None
    body_text: str
    body_html: str | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    received_at: datetime | None = None


class ReplyClassifyResult(BaseModel):
    classification: ReplyClassification
    confidence: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0)
    summary: str
    suggested_action: str


class ReplyResponse(TimestampedSchema):
    email_id: uuid.UUID | None = None
    company_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    from_email: str
    from_name: str | None = None
    subject: str | None = None
    body_text: str
    classification: ReplyClassification
    classification_confidence: float | None = None
    sentiment_score: float | None = None
    ai_summary: str | None = None
    received_at: datetime
    reviewed: bool


class ReplyReviewRequest(BaseModel):
    override_classification: ReplyClassification | None = None
    note: str | None = None
