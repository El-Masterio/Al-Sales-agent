"""
app/models/base.py
==================
SQLAlchemy declarative base and shared mixins.

Every ORM model inherits from Base.
Models that need a UUID PK + timestamps inherit from BaseModel.

Design rules:
- All PKs are UUID v4 (server-generated via uuid_generate_v4())
- created_at / updated_at are always TIMESTAMPTZ
- updated_at is managed by a DB trigger (schema.sql) AND replicated
  here via SQLAlchemy's onupdate for in-process consistency
- Enum types mirror the PostgreSQL enums in schema.sql exactly
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column

# ---------------------------------------------------------------------------
# Naming convention — ensures Alembic can autogenerate constraint names
# ---------------------------------------------------------------------------
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """
    Common declarative base for all ORM models.
    Attach metadata with naming convention so Alembic can diff correctly.
    """

    metadata = metadata

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """
        Shallow dict representation of the model.
        Excludes SQLAlchemy internals and any keys in `exclude`.
        """
        exclude = exclude or set()
        return {
            col.name: getattr(self, col.name)
            for col in self.__table__.columns
            if col.name not in exclude
        }

    def __repr__(self) -> str:
        pk_col = self.__table__.primary_key.columns.values()[0].name
        pk_val = getattr(self, pk_col, None)
        return f"<{self.__class__.__name__} {pk_col}={pk_val!r}>"


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class UUIDMixin:
    """
    UUID primary key, server-generated.
    Uses PostgreSQL's uuid_generate_v4() as the default so the DB owns
    generation; Python also supplies a fallback default for test environments
    without the extension.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        default=uuid.uuid4,
        index=False,   # PK index is implicit
    )


class TimestampMixin:
    """
    created_at and updated_at columns.
    updated_at is set by the DB trigger on the server side;
    the Python-side onupdate keeps it current for objects modified
    within the same session before commit.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        nullable=False,
        index=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        onupdate=datetime.utcnow,
        nullable=False,
        index=False,
    )


class BaseModel(UUIDMixin, TimestampMixin):
    """
    Convenience base that includes UUID PK + timestamps.
    Inherit in the ORM model AFTER Base:

        class Company(Base, BaseModel):
            __tablename__ = "companies"
    """

    __abstract__ = True


# ---------------------------------------------------------------------------
# PostgreSQL enum types
# Defined here as Python enums; SQLAlchemy maps them to the PG enum type.
# The `name` kwarg MUST match the enum name in schema.sql exactly.
# ---------------------------------------------------------------------------

import enum as _enum

from sqlalchemy import Enum as SAEnum


class CompanySize(_enum.StrEnum):
    SIZE_1_10    = "1-10"
    SIZE_11_50   = "11-50"
    SIZE_51_200  = "51-200"
    SIZE_201_500 = "201-500"
    SIZE_501_1K  = "501-1000"
    SIZE_1K_5K   = "1001-5000"
    SIZE_5K_PLUS = "5000+"


class LeadStatus(_enum.StrEnum):
    NEW               = "new"
    RESEARCHING       = "researching"
    READY_TO_CONTACT  = "ready_to_contact"
    CONTACTED         = "contacted"
    REPLIED           = "replied"
    INTERESTED        = "interested"
    MEETING_SCHEDULED = "meeting_scheduled"
    MEETING_COMPLETED = "meeting_completed"
    QUALIFIED         = "qualified"
    PROPOSAL_SENT     = "proposal_sent"
    NEGOTIATING       = "negotiating"
    CLOSED_WON        = "closed_won"
    CLOSED_LOST       = "closed_lost"
    NOT_INTERESTED    = "not_interested"
    UNSUBSCRIBED      = "unsubscribed"
    BOUNCED           = "bounced"


class EmailStatus(_enum.StrEnum):
    DRAFT        = "draft"
    QUEUED       = "queued"
    SENT         = "sent"
    DELIVERED    = "delivered"
    OPENED       = "opened"
    CLICKED      = "clicked"
    REPLIED      = "replied"
    BOUNCED      = "bounced"
    FAILED       = "failed"
    UNSUBSCRIBED = "unsubscribed"


class EmailType(_enum.StrEnum):
    INITIAL_OUTREACH      = "initial_outreach"
    FOLLOW_UP_1           = "follow_up_1"
    FOLLOW_UP_2           = "follow_up_2"
    FOLLOW_UP_3           = "follow_up_3"
    REPLY                 = "reply"
    MEETING_CONFIRMATION  = "meeting_confirmation"
    MEETING_REMINDER      = "meeting_reminder"
    PROPOSAL              = "proposal"


class ReplyClassification(_enum.StrEnum):
    INTERESTED       = "interested"
    MAYBE_LATER      = "maybe_later"
    NOT_INTERESTED   = "not_interested"
    NEEDS_PRICING    = "needs_pricing"
    WANTS_DEMO       = "wants_demo"
    OUT_OF_OFFICE    = "out_of_office"
    WRONG_PERSON     = "wrong_person"
    UNSUBSCRIBE      = "unsubscribe_request"
    QUESTION         = "question"
    POSITIVE_GENERAL = "positive_general"
    NEGATIVE_GENERAL = "negative_general"
    UNCLASSIFIED     = "unclassified"


class MeetingStatus(_enum.StrEnum):
    PROPOSED    = "proposed"
    CONFIRMED   = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED   = "cancelled"
    COMPLETED   = "completed"
    NO_SHOW     = "no_show"


class CampaignStatus(_enum.StrEnum):
    DRAFT     = "draft"
    ACTIVE    = "active"
    PAUSED    = "paused"
    COMPLETED = "completed"
    ARCHIVED  = "archived"


class TaskStatus(_enum.StrEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class UserRole(_enum.StrEnum):
    ADMIN    = "admin"
    SALES_REP = "sales_rep"
    VIEWER   = "viewer"


# ---------------------------------------------------------------------------
# SQLAlchemy column type shortcuts
# These map Python enums to the PostgreSQL named enum types in schema.sql.
# create_constraint=False because the constraint is already in the DB schema.
# ---------------------------------------------------------------------------

def pg_enum(enum_class: type[_enum.Enum], pg_name: str) -> SAEnum:
    return SAEnum(
        enum_class,
        name=pg_name,
        create_constraint=False,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
    )


CompanySizeType    = pg_enum(CompanySize,         "company_size")
LeadStatusType     = pg_enum(LeadStatus,          "lead_status")
EmailStatusType    = pg_enum(EmailStatus,         "email_status")
EmailTypeType      = pg_enum(EmailType,           "email_type")
ReplyClassType     = pg_enum(ReplyClassification, "reply_classification")
MeetingStatusType  = pg_enum(MeetingStatus,       "meeting_status")
CampaignStatusType = pg_enum(CampaignStatus,      "campaign_status")
TaskStatusType     = pg_enum(TaskStatus,          "task_status")
UserRoleType       = pg_enum(UserRole,            "user_role")


# ---------------------------------------------------------------------------
# String column length constants (DRY — used across models)
# ---------------------------------------------------------------------------
class StrLen:
    SHORT  = 100
    MEDIUM = 255
    LONG   = 1000
    URL    = 2048
    EMAIL  = 320       # RFC 5321 max
    PHONE  = 20
    UUID   = 36
