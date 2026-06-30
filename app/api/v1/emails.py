"""
app/api/v1/emails.py
====================
Email endpoints + tracking pixel/click-redirect routes.

The tracking routes are intentionally UNAUTHENTICATED (they're hit by
recipients' mail clients) and return fast — heavy processing is deferred.
"""

from __future__ import annotations

import uuid
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, Response

from app.api.deps import CurrentUser, DbSession
from app.core.database import get_db_context
from app.repositories.email_repository import EmailRepository
from app.schemas.email import EmailDetailResponse, EmailResponse
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/emails", tags=["emails"])

# 1x1 transparent PNG
_PIXEL_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001a5f645400000000049454e44ae426082"
)


@router.get("/{company_id}/list", response_model=PaginatedResponse[EmailResponse])
async def list_company_emails(
    company_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> PaginatedResponse[EmailResponse]:
    repo = EmailRepository(db)
    emails = await repo.get_by_company(company_id)
    return PaginatedResponse.create(
        items=[EmailResponse.model_validate(e) for e in emails],
        total=len(emails),
        page=1,
        page_size=len(emails) or 1,
    )


@router.get("/detail/{email_id}", response_model=EmailDetailResponse)
async def get_email(email_id: uuid.UUID, db: DbSession, user: CurrentUser) -> EmailDetailResponse:
    repo = EmailRepository(db)
    email = await repo.get(email_id)
    if email is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    return EmailDetailResponse.model_validate(email)


# ── Tracking routes (unauthenticated) ─────────────────────────────────────────

tracking_router = APIRouter(prefix="/t", tags=["tracking"])


@tracking_router.get("/{tracking_id}/open.png")
async def track_open(tracking_id: uuid.UUID, request: Request) -> Response:
    """Tracking pixel — records an open event, returns a 1x1 PNG."""
    async with get_db_context() as db:
        repo = EmailRepository(db)
        email = await repo.get_by_tracking_id(tracking_id)
        if email:
            email.record_open()
            await repo.add_event(
                email.id,
                "opened",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
    return Response(content=_PIXEL_BYTES, media_type="image/png")


@tracking_router.get("/{tracking_id}/click")
async def track_click(tracking_id: uuid.UUID, request: Request, url: str = Query(...)) -> RedirectResponse:
    """Click tracking — records a click event, then redirects to the original URL."""
    target = unquote(url)
    async with get_db_context() as db:
        repo = EmailRepository(db)
        email = await repo.get_by_tracking_id(tracking_id)
        if email:
            email.record_click()
            await repo.add_event(
                email.id,
                "clicked",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                click_url=target,
            )
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
