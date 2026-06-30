"""
app/models/user.py
==================
User: internal user of the Sales Agent platform (admin / sales_rep / viewer).
Stores encrypted Google Calendar OAuth2 token for meeting booking.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, StrLen, UserRole, UserRoleType

if TYPE_CHECKING:
    from app.models.api_key import ApiKey
    from app.models.campaign import Campaign
    from app.models.company import Company
    from app.models.meeting import Meeting


class User(Base, BaseModel):
    """
    A platform user. Sales reps own campaigns, get assigned leads,
    and have meetings booked on their connected Google Calendar.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(StrLen.EMAIL), nullable=False, unique=True, index=True
    )
    full_name: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(StrLen.LONG), nullable=False)
    role: Mapped[str] = mapped_column(
        UserRoleType, nullable=False, server_default=text("'sales_rep'"), default=UserRole.SALES_REP
    )
    avatar_url: Mapped[str | None] = mapped_column(String(StrLen.URL))
    timezone: Mapped[str] = mapped_column(
        String(StrLen.SHORT), nullable=False, server_default=text("'UTC'"), default="UTC"
    )

    # ── Google Calendar integration ───────────────────────────────────────────
    # Encrypted via app.services.security.encrypt_token before storage
    google_calendar_token: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    google_calendar_id: Mapped[str | None] = mapped_column(String(StrLen.MEDIUM))

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Relationships ─────────────────────────────────────────────────────────
    assigned_companies: Mapped[list[Company]] = relationship(
        "Company",
        foreign_keys="Company.assigned_to_id",
        lazy="select",
    )
    owned_campaigns: Mapped[list[Campaign]] = relationship(
        "Campaign",
        foreign_keys="Campaign.owner_id",
        lazy="select",
    )
    meetings: Mapped[list[Meeting]] = relationship(
        "Meeting",
        foreign_keys="Meeting.assigned_rep_id",
        lazy="select",
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        "ApiKey",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def has_calendar_connected(self) -> bool:
        return self.google_calendar_token is not None

    @property
    def can_manage_campaigns(self) -> bool:
        return self.role in {UserRole.ADMIN, UserRole.SALES_REP}

    # ── Mutators ──────────────────────────────────────────────────────────────

    def record_login(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.last_login_at = _dt.now(_tz.utc)

    def connect_calendar(self, token_data: dict[str, Any], calendar_id: str) -> None:
        self.google_calendar_token = token_data
        self.google_calendar_id = calendar_id

    def disconnect_calendar(self) -> None:
        self.google_calendar_token = None
        self.google_calendar_id = None

    def deactivate(self) -> None:
        self.is_active = False
