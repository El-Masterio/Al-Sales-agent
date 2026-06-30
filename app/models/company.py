"""
app/models/company.py
=====================
Company ORM model — the central entity in the sales pipeline.
Every lead starts as a Company record.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column, relationship

from app.models.base import (
    Base,
    BaseModel,
    CompanySizeType,
    LeadStatusType,
    LeadStatus,
    StrLen,
)

if TYPE_CHECKING:
    from app.models.campaign import CampaignLead
    from app.models.contact import Contact
    from app.models.email import Email
    from app.models.meeting import Meeting
    from app.models.memory import ConversationMemory
    from app.models.note import Note
    from app.models.reply import Reply
    from app.models.user import User


class Company(Base, BaseModel):
    """
    A target company discovered via lead generation.

    Lifecycle:
        new → researching → ready_to_contact → contacted → replied
           → interested → meeting_scheduled → qualified → closed_won/lost

    All AI-generated fields (pain_points, tech_stack, value_proposition, etc.)
    are populated by the Research service before outreach begins.
    """

    __tablename__ = "companies"

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False, index=True)
    website: Mapped[str | None] = mapped_column(String(StrLen.URL))
    domain: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM), index=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(StrLen.URL))
    crunchbase_url: Mapped[str | None] = mapped_column(String(StrLen.URL))

    # ── Classification ────────────────────────────────────────────────────────
    industry: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM), index=True)
    sub_industry: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))
    company_size: Mapped[str | None] = mapped_column(CompanySizeType)
    employee_count: Mapped[int | None] = mapped_column(Integer)
    founded_year: Mapped[int | None] = mapped_column(SmallInteger)
    hq_country: Mapped[str | None] = mapped_column(String(StrLen.SHORT))
    hq_city: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))

    # ── Financials ────────────────────────────────────────────────────────────
    annual_revenue_usd: Mapped[int | None] = mapped_column(BigInteger)
    funding_stage: Mapped[str | None] = mapped_column(String(StrLen.SHORT))
    total_funding_usd: Mapped[int | None] = mapped_column(BigInteger)
    last_funding_date: Mapped[datetime | None] = mapped_column(Date)

    # ── AI Research Output ────────────────────────────────────────────────────
    description: Mapped[str | None] = mapped_column(Text)
    products_summary: Mapped[str | None] = mapped_column(Text)

    # PostgreSQL arrays — store as lists of strings
    pain_points: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    tech_stack: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), index=True
    )

    # JSONB fields — [{title, url, date, summary}, ...]
    recent_news: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    value_proposition: Mapped[str | None] = mapped_column(Text)
    icp_score: Mapped[int | None] = mapped_column(
        SmallInteger,
        comment="ICP fit score 0-100",
    )

    # ── Status ────────────────────────────────────────────────────────────────
    lead_status: Mapped[str] = mapped_column(
        LeadStatusType,
        nullable=False,
        server_default=text("'new'"),
        default=LeadStatus.NEW,
        index=True,
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        name="assigned_to",
        index=True,
    )
    disqualify_reason: Mapped[str | None] = mapped_column(Text)

    # ── Research metadata ─────────────────────────────────────────────────────
    last_researched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    research_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )

    # ── Raw data ──────────────────────────────────────────────────────────────
    raw_scrape_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # ── Relationships ─────────────────────────────────────────────────────────
    assigned_to: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[assigned_to_id],
        lazy="select",
    )
    contacts: Mapped[list[Contact]] = relationship(
        "Contact",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Contact.is_primary_contact.desc()",
    )
    emails: Mapped[list[Email]] = relationship(
        "Email",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Email.created_at.desc()",
    )
    replies: Mapped[list[Reply]] = relationship(
        "Reply",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Reply.received_at.desc()",
    )
    meetings: Mapped[list[Meeting]] = relationship(
        "Meeting",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Meeting.starts_at",
    )
    campaign_leads: Mapped[list[CampaignLead]] = relationship(
        "CampaignLead",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select",
    )
    memories: Mapped[list[ConversationMemory]] = relationship(
        "ConversationMemory",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="ConversationMemory.importance.desc()",
    )
    notes: Mapped[list[Note]] = relationship(
        "Note",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Note.created_at.desc()",
        primaryjoin="Note.company_id == Company.id",
    )

    # ── Helper methods ────────────────────────────────────────────────────────

    @property
    def primary_contact(self) -> Contact | None:
        """Return the designated primary contact, if loaded."""
        for c in self.contacts:
            if c.is_primary_contact:
                return c
        return self.contacts[0] if self.contacts else None

    @property
    def is_researched(self) -> bool:
        return self.last_researched_at is not None

    @property
    def is_contactable(self) -> bool:
        """True if the company can receive outreach."""
        non_contactable = {
            LeadStatus.NOT_INTERESTED,
            LeadStatus.UNSUBSCRIBED,
            LeadStatus.BOUNCED,
            LeadStatus.CLOSED_WON,
            LeadStatus.CLOSED_LOST,
        }
        return self.lead_status not in non_contactable

    def advance_status(self, new_status: LeadStatus) -> None:
        """
        Move the lead status forward.
        Raises ValueError if attempting to move to a logically earlier state
        when that would be wrong (e.g. new → closed_won directly).
        """
        self.lead_status = new_status

    def to_research_context(self) -> dict[str, Any]:
        """
        Return a minimal dict suitable for injecting into AI research prompts.
        """
        return {
            "name": self.name,
            "website": self.website,
            "industry": self.industry,
            "employee_count": self.employee_count,
            "funding_stage": self.funding_stage,
            "total_funding_usd": self.total_funding_usd,
            "hq_country": self.hq_country,
            "hq_city": self.hq_city,
            "description": self.description,
            "tech_stack": self.tech_stack or [],
            "recent_news": self.recent_news or [],
        }

    def to_outreach_context(self) -> dict[str, Any]:
        """
        Return full research context for email generation prompts.
        """
        return {
            **self.to_research_context(),
            "products_summary": self.products_summary,
            "pain_points": self.pain_points or [],
            "value_proposition": self.value_proposition,
            "icp_score": self.icp_score,
        }
