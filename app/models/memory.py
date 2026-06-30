"""
app/models/memory.py
====================
ConversationMemory: AI long-term memory per company/contact.
Stores facts, preferences, objections, and milestones as vector embeddings
for semantic retrieval during email generation and reply handling.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, StrLen

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.contact import Contact

EMBEDDING_DIM = 1536  # text-embedding-3-small


class ConversationMemory(Base, BaseModel):
    """
    A single unit of long-term memory about a company or contact.

    memory_type values:
        summary     — rolling conversation summary
        preference  — stated preference ("prefers async demos")
        objection   — sales objection raised ("too expensive right now")
        fact        — factual detail learned ("uses Snowflake, not Redshift")
        milestone   — pipeline milestone ("demo completed", "proposal sent")

    Retrieval:
        Semantic search via cosine similarity on `embedding`, filtered by
        company_id and optionally memory_type. Used by the LangGraph agent
        to inject relevant context into prompts without re-reading full
        email history every time.
    """

    __tablename__ = "conversation_memory"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
    )

    memory_type: Mapped[str] = mapped_column(
        String(StrLen.SHORT), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    # ── Context ───────────────────────────────────────────────────────────────
    source_type: Mapped[str | None] = mapped_column(String(StrLen.SHORT))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    importance: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("5"), default=5
    )

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Relationships ─────────────────────────────────────────────────────────
    company: Mapped[Company] = relationship(
        "Company", back_populates="memories", lazy="select"
    )
    contact: Mapped[Contact | None] = relationship(
        "Contact", back_populates="memories", lazy="select"
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        from datetime import datetime, timezone

        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_high_importance(self) -> bool:
        return self.importance >= 8

    # ── Factory helpers ───────────────────────────────────────────────────────

    @classmethod
    def from_objection(
        cls,
        company_id: uuid.UUID,
        content: str,
        embedding: list[float],
        contact_id: uuid.UUID | None = None,
        source_id: uuid.UUID | None = None,
    ) -> ConversationMemory:
        return cls(
            company_id=company_id,
            contact_id=contact_id,
            memory_type="objection",
            content=content,
            embedding=embedding,
            source_type="reply",
            source_id=source_id,
            importance=8,
        )

    @classmethod
    def from_preference(
        cls,
        company_id: uuid.UUID,
        content: str,
        embedding: list[float],
        contact_id: uuid.UUID | None = None,
    ) -> ConversationMemory:
        return cls(
            company_id=company_id,
            contact_id=contact_id,
            memory_type="preference",
            content=content,
            embedding=embedding,
            importance=6,
        )

    @classmethod
    def from_milestone(
        cls,
        company_id: uuid.UUID,
        content: str,
        embedding: list[float],
        source_type: str,
        source_id: uuid.UUID,
    ) -> ConversationMemory:
        return cls(
            company_id=company_id,
            memory_type="milestone",
            content=content,
            embedding=embedding,
            source_type=source_type,
            source_id=source_id,
            importance=7,
        )
