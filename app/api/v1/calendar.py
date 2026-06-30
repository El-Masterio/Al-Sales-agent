"""
app/api/v1/calendar.py
======================
Google Calendar OAuth2 connect/disconnect endpoints.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.database import get_db_context
from app.repositories.user_repository import UserRepository
from app.schemas.common import MessageResponse
from app.services.calendar_service import calendar_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/connect")
async def connect_calendar(user: CurrentUser) -> dict[str, str]:
    """Return the Google consent URL for the current user to authorize calendar access."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar integration not configured",
        )
    auth_url = calendar_service.get_authorization_url(user.id)
    return {"authorization_url": auth_url}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """
    OAuth2 redirect target. Exchanges the code for tokens and stores them
    (encrypted) on the user identified by `state`.
    """
    try:
        user_id = uuid.UUID(state)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state")

    token_data = calendar_service.exchange_code(code)
    encrypted = calendar_service.encrypt_token(token_data)

    async with get_db_context() as db:
        users = UserRepository(db)
        user = await users.get(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user.connect_calendar(encrypted, "primary")

    return RedirectResponse(url=f"{settings.frontend_url_str}/settings?calendar=connected")


@router.post("/disconnect", response_model=MessageResponse)
async def disconnect_calendar(db: DbSession, user: CurrentUser) -> MessageResponse:
    users = UserRepository(db)
    db_user = await users.get(user.id)
    if db_user:
        db_user.disconnect_calendar()
        await db.flush()
    return MessageResponse(message="Calendar disconnected")
