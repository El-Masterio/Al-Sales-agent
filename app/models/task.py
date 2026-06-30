"""
app/models/task.py
==================
Task: Celery task audit log. Every dispatched task gets a row here
for observability — retried automatically up to max_retries, status
tracked through pending → running → completed/failed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, StrLen, TaskStatus, TaskStatusType

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.company import Company
    from app.models.email import Email


class Task(Base):
    """
    Audit log row for a single Celery task execution.
    Not a BaseModel subclass — uses created_at only (no updated_at semantics
    needed; status transitions are tracked via explicit timestamp columns).
    """

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        default=uuid.uuid4,
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(StrLen.MEDIUM), unique=True, index=True
    )
    task_name: Mapped[str] = mapped_column(String(StrLen.MEDIUM), nullable=False, index=True)
    task_args: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'"), default=dict
    )
    status: Mapped[str] = mapped_column(
        TaskStatusType,
        nullable=False,
        server_default=text("'pending'"),
        default=TaskStatus.PENDING,
        index=True,
    )

    # ── Relations (nullable — set depending on task type) ────────────────────
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id", ondelete="SET NULL")
    )

    # ── Execution ─────────────────────────────────────────────────────────────
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=datetime.utcnow,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # ── Result ────────────────────────────────────────────────────────────────
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
    max_retries: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("3"), default=3
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=datetime.utcnow,
    )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    @property
    def is_terminal(self) -> bool:
        return self.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    # ── Mutators ──────────────────────────────────────────────────────────────

    def mark_running(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.status = TaskStatus.RUNNING
        self.started_at = _dt.now(_tz.utc)

    def mark_completed(self, result: dict[str, Any] | None = None) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.status = TaskStatus.COMPLETED
        self.completed_at = _dt.now(_tz.utc)
        self.result = result
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)

    def mark_failed(self, error: str) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        self.status = TaskStatus.FAILED
        self.completed_at = _dt.now(_tz.utc)
        self.error = error
        self.retry_count += 1
