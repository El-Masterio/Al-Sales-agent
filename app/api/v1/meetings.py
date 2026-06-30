"""
app/api/v1/meetings.py
======================
Meeting endpoints: availability, book, list upcoming, update/cancel.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, RequireSalesRep
from app.repositories.meeting_repository import MeetingRepository
from app.schemas.common import PaginatedResponse
from app.schemas.meeting import (
    AvailabilityRequest,
    AvailabilityResponse,
    MeetingBookRequest,
    MeetingResponse,
    MeetingUpdateRequest,
)
from app.services.meeting_service import MeetingService

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.post("/availability", response_model=AvailabilityResponse)
async def get_availability(
    req: AvailabilityRequest, db: DbSession, user: CurrentUser
) -> AvailabilityResponse:
    service = MeetingService(db)
    try:
        tz, slots = await service.get_availability(req)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rep not found")
    return AvailabilityResponse(rep_id=req.rep_id, timezone=tz, slots=slots)


@router.post("", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
async def book_meeting(req: MeetingBookRequest, db: DbSession, user: RequireSalesRep) -> MeetingResponse:
    service = MeetingService(db)
    try:
        meeting = await service.book_meeting(req)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return MeetingResponse.model_validate(meeting)


@router.get("/upcoming", response_model=PaginatedResponse[MeetingResponse])
async def list_upcoming(db: DbSession, user: CurrentUser) -> PaginatedResponse[MeetingResponse]:
    repo = MeetingRepository(db)
    meetings = await repo.get_upcoming()
    return PaginatedResponse.create(
        items=[MeetingResponse.model_validate(m) for m in meetings],
        total=len(meetings),
        page=1,
        page_size=len(meetings) or 1,
    )


@router.patch("/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    meeting_id: uuid.UUID, data: MeetingUpdateRequest, db: DbSession, user: RequireSalesRep
) -> MeetingResponse:
    repo = MeetingRepository(db)
    meeting = await repo.get(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    updated = await repo.update(meeting, **data.model_dump(exclude_unset=True, exclude_none=True))
    return MeetingResponse.model_validate(updated)


@router.delete("/{meeting_id}", response_model=MeetingResponse)
async def cancel_meeting(meeting_id: uuid.UUID, db: DbSession, user: RequireSalesRep) -> MeetingResponse:
    service = MeetingService(db)
    try:
        meeting = await service.cancel_meeting(meeting_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return MeetingResponse.model_validate(meeting)
