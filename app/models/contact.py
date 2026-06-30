"""
app/models/contact.py
=====================
Contact ORM model — decision makers and key people at target companies.
One company can have many contacts; one contact is flagged as primary.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, StrLen

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.email import Email
    from app.models.meeting import Meeting
    from app.models.memory import ConversationMemory
    from app.models.note import Note
    from app.models.reply import Reply


class Contact(Base, BaseModel):
    """
    A person at a target company.

    Enrichment flow:
        1. Name + title scraped from LinkedIn / website
        2. Email found via Hunter.io / Apollo
        3. Email verified (MX check + Hunter confidence score)
        4. is_decision_maker determined by title heuristic or AI classification
        5. is_primary_contact = True for the person we should email first
    """

    __tablename__ = "contacts"

    # ── Company FK ────────────────────────────────────────────────────────────
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    first_name: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))
    title: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))

    # Seniority bucket — used for ICP scoring and targeting logic
    # Values: c-level | vp | director | manager | ic | unknown
    seniority: Mapped[str | None] = mapped_column(String(StrLen.SHORT))

    # Department bucket: engineering | marketing | sales | product | finance | legal | ops
    department: Mapped[str | None] = mapped_column(String(StrLen.SHORT))

    # ── Contact info ──────────────────────────────────────────────────────────
    email: Mapped[str | None] = mapped_column(
        String(StrLen.EMAIL),
        unique=True,
        index=True,
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    email_bounce: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    phone: Mapped[str | None] = mapped_column(String(StrLen.PHONE))
    linkedin_url: Mapped[str | None] = mapped_column(String(StrLen.URL))
    twitter_url: Mapped[str | None] = mapped_column(String(StrLen.URL))

    # ── Decision-maker signals ────────────────────────────────────────────────
    is_decision_maker: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    is_primary_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    # ── Enrichment metadata ───────────────────────────────────────────────────
    enrichment_source: Mapped[str | None] = mapped_column(String(StrLen.SHORT))
    enrichment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # ── Opt-out ───────────────────────────────────────────────────────────────
    unsubscribed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)

    # ── Relationships ─────────────────────────────────────────────────────────
    company: Mapped[Company] = relationship(
        "Company",
        back_populates="contacts",
        lazy="select",
    )
    emails: Mapped[list[Email]] = relationship(
        "Email",
        back_populates="contact",
        lazy="select",
        order_by="Email.created_at.desc()",
    )
    replies: Mapped[list[Reply]] = relationship(
        "Reply",
        back_populates="contact",
        lazy="select",
        order_by="Reply.received_at.desc()",
    )
    meetings: Mapped[list[Meeting]] = relationship(
        "Meeting",
        back_populates="contact",
        lazy="select",
        order_by="Meeting.starts_at",
    )
    memories: Mapped[list[ConversationMemory]] = relationship(
        "ConversationMemory",
        back_populates="contact",
        lazy="select",
    )
    note_records: Mapped[list[Note]] = relationship(
        "Note",
        back_populates="contact",
        cascade="all, delete-orphan",
        lazy="select",
        primaryjoin="Note.contact_id == Contact.id",
    )

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def full_name(self) -> str:
        parts = [self.first_name]
        if self.last_name:
            parts.append(self.last_name)
        return " ".join(parts)

    @property
    def display_name(self) -> str:
        """Full name + title for display."""
        if self.title:
            return f"{self.full_name}, {self.title}"
        return self.full_name

    @property
    def is_emailable(self) -> bool:
        """True if we have a valid, non-bounced, non-opted-out email."""
        return (
            self.email is not None
            and not self.email_bounce
            and not self.unsubscribed
        )

    @property
    def is_senior(self) -> bool:
        """True for C-level, VP, or Director — decision-maker tier."""
        return self.seniority in {"c-level", "vp", "director"}

    # ── Helper methods ────────────────────────────────────────────────────────

    def mark_unsubscribed(self) -> None:
        from datetime import datetime, timezone
        self.unsubscribed = True
        self.unsubscribed_at = datetime.now(timezone.utc)

    def mark_bounced(self) -> None:
        self.email_bounce = True

    def to_prompt_context(self) -> dict[str, Any]:
        """Minimal dict for injecting into AI email generation prompts."""
        return {
            "first_name": self.first_name,
            "full_name": self.full_name,
            "title": self.title or "decision maker",
            "department": self.department,
            "seniority": self.seniority,
            "email": self.email,
            "linkedin_url": self.linkedin_url,
        }

    @classmethod
    def infer_seniority(cls, title: str) -> str:
        """
        Heuristic title → seniority bucket.
        Used during contact enrichment when the API doesn't provide seniority.
        """
        if not title:
            return "unknown"
        t = title.lower()
        if any(k in t for k in ("ceo", "cto", "coo", "cfo", "chief", "founder", "owner", "president")):
            return "c-level"
        if "vp" in t or "vice president" in t:
            return "vp"
        if "director" in t or "head of" in t:
            return "director"
        if "manager" in t or "lead" in t:
            return "manager"
        return "ic"

    @classmethod
    def infer_department(cls, title: str) -> str:
        """Heuristic title → department bucket."""
        if not title:
            return "unknown"
        t = title.lower()
        if any(k in t for k in ("engineer", "developer", "architect", "devops", "sre", "cto")):
            return "engineering"
        if any(k in t for k in ("marketing", "growth", "brand", "content", "seo", "cmo")):
            return "marketing"
        if any(k in t for k in ("sales", "account", "business development", "revenue", "cso")):
            return "sales"
        if any(k in t for k in ("product", "ux", "design", "cpo")):
            return "product"
        if any(k in t for k in ("finance", "accounting", "cfo", "treasury")):
            return "finance"
        if any(k in t for k in ("legal", "counsel", "compliance", "clo")):
            return "legal"
        if any(k in t for k in ("operation", "coo", "logistics", "supply")):
            return "operations"
        return "unknown"
