"""
app/models/api_key.py
=====================
ApiKey: encrypted third-party API key storage, scoped per user.
Encryption handled by app.services.security; this model only stores
the encrypted blob and a display-safe preview.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, StrLen

if TYPE_CHECKING:
    from app.models.user import User


class ApiKey(Base, BaseModel):
    """
    An encrypted API key for a third-party service (OpenAI, SendGrid,
    Hunter, Clearbit, Google) belonging to a specific user.

    key_hash:    pgcrypto/Fernet-encrypted ciphertext, never returned via API
    key_preview: last 4 characters only, safe to display in UI
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "service", "label", name="uq_api_keys_user_service_label"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service: Mapped[str] = mapped_column(String(StrLen.SHORT), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(StrLen.LONG), nullable=False)
    key_preview: Mapped[str] = mapped_column(String(8), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="api_keys", lazy="select")

    # ── Mutators ──────────────────────────────────────────────────────────────

    def record_use(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.last_used_at = _dt.now(_tz.utc)

    def deactivate(self) -> None:
        self.is_active = False
