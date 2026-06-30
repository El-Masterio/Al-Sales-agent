"""
app/models/__init__.py
======================
Central import registry for all ORM models.

This module MUST import every model class so that:
  1. SQLAlchemy's mapper configuration resolves all relationship() string
     references (e.g. relationship("Contact")) at import time.
  2. Alembic's autogenerate can see the full metadata when diffing.

Always import models via `from app.models import Company, Contact, ...`
rather than reaching into individual submodules, to guarantee this
registration has already happened.
"""

from __future__ import annotations

from app.models.api_key import ApiKey
from app.models.base import (
    Base,
    BaseModel,
    CampaignStatus,
    CompanySize,
    EmailStatus,
    EmailType,
    LeadStatus,
    MeetingStatus,
    ReplyClassification,
    TaskStatus,
    UserRole,
)
from app.models.campaign import Campaign, CampaignLead
from app.models.company import Company
from app.models.contact import Contact
from app.models.daily_stats import DailyStats, WebhookLog
from app.models.email import Email, EmailEvent
from app.models.meeting import Meeting
from app.models.memory import ConversationMemory
from app.models.note import Note
from app.models.reply import Reply
from app.models.task import Task
from app.models.user import User

__all__ = [
    "Base",
    "BaseModel",
    # Enums
    "CampaignStatus",
    "CompanySize",
    "EmailStatus",
    "EmailType",
    "LeadStatus",
    "MeetingStatus",
    "ReplyClassification",
    "TaskStatus",
    "UserRole",
    # Models
    "ApiKey",
    "Campaign",
    "CampaignLead",
    "Company",
    "Contact",
    "ConversationMemory",
    "DailyStats",
    "Email",
    "EmailEvent",
    "Meeting",
    "Note",
    "Reply",
    "Task",
    "User",
    "WebhookLog",
]
