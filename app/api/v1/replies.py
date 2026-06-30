"""
app/api/v1/replies.py
=====================
Reply endpoints + inbound email webhook (SendGrid Inbound Parse / SES).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession
from app.models.base import ReplyClassification
from app.repositories.reply_repository import ReplyRepository
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.email import InboundEmailWebhook, ReplyResponse, ReplyReviewRequest
from app.services.reply_service import ReplyService

router = APIRouter(prefix="/replies", tags=["replies"])


@router.get("/pending-review", response_model=PaginatedResponse[ReplyResponse])
async def list_pending_review(db: DbSession, user: CurrentUser) -> PaginatedResponse[ReplyResponse]:
    repo = ReplyRepository(db)
    replies = await repo.get_pending_review()
    return PaginatedResponse.create(
        items=[ReplyResponse.model_validate(r) for r in replies],
        total=len(replies),
        page=1,
        page_size=len(replies) or 1,
    )


@router.get("/{company_id}", response_model=PaginatedResponse[ReplyResponse])
async def list_company_replies(
    company_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> PaginatedResponse[ReplyResponse]:
    repo = ReplyRepository(db)
    replies = await repo.get_by_company(company_id)
    return PaginatedResponse.create(
        items=[ReplyResponse.model_validate(r) for r in replies],
        total=len(replies),
        page=1,
        page_size=len(replies) or 1,
    )


@router.post("/{reply_id}/review", response_model=ReplyResponse)
async def review_reply(
    reply_id: uuid.UUID, data: ReplyReviewRequest, db: DbSession, user: CurrentUser
) -> ReplyResponse:
    repo = ReplyRepository(db)
    reply = await repo.get(reply_id)
    if reply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reply not found")
    reply.mark_reviewed(user.id, data.override_classification)
    await db.flush()
    return ReplyResponse.model_validate(reply)


# ── Inbound webhook (unauthenticated — verified via provider signature) ───────

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post("/inbound-email", response_model=MessageResponse)
async def inbound_email_webhook(payload: InboundEmailWebhook, db: DbSession) -> MessageResponse:
    """
    Receives a normalized inbound email. Persists it, then queues async
    classification + action processing.
    """
    service = ReplyService(db)
    reply = await service.ingest_inbound(payload)
    if reply is None:
        return MessageResponse(message="Reply ignored (unknown sender)", success=False)

    await db.commit()

    from app.workers.tasks import process_reply_task

    process_reply_task.delay(str(reply.id))
    return MessageResponse(message="Reply received and queued for processing")
