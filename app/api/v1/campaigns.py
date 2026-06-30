"""
app/api/v1/campaigns.py
=======================
Campaign endpoints: CRUD, activate/pause, add leads, stats.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, RequireSalesRep
from app.repositories.campaign_repository import CampaignRepository
from app.schemas.campaign import (
    AddLeadsToCampaignRequest,
    CampaignCreate,
    CampaignResponse,
    CampaignStatsResponse,
    CampaignUpdate,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.services.campaign_service import CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=PaginatedResponse[CampaignResponse])
async def list_campaigns(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[CampaignResponse]:
    repo = CampaignRepository(db)
    offset = (page - 1) * page_size
    campaigns = await repo.list(offset=offset, limit=page_size)
    total = await repo.count()
    return PaginatedResponse.create(
        items=[CampaignResponse.model_validate(c) for c in campaigns],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(data: CampaignCreate, db: DbSession, user: RequireSalesRep) -> CampaignResponse:
    service = CampaignService(db)
    campaign = await service.create_campaign(user.id, data)
    return CampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CampaignResponse:
    repo = CampaignRepository(db)
    campaign = await repo.get(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID, data: CampaignUpdate, db: DbSession, user: RequireSalesRep
) -> CampaignResponse:
    service = CampaignService(db)
    try:
        campaign = await service.update_campaign(campaign_id, data)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.post("/{campaign_id}/activate", response_model=CampaignResponse)
async def activate_campaign(campaign_id: uuid.UUID, db: DbSession, user: RequireSalesRep) -> CampaignResponse:
    service = CampaignService(db)
    try:
        campaign = await service.activate_campaign(campaign_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(campaign_id: uuid.UUID, db: DbSession, user: RequireSalesRep) -> CampaignResponse:
    service = CampaignService(db)
    try:
        campaign = await service.pause_campaign(campaign_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.post("/{campaign_id}/leads", response_model=MessageResponse)
async def add_leads(
    campaign_id: uuid.UUID,
    data: AddLeadsToCampaignRequest,
    db: DbSession,
    user: RequireSalesRep,
) -> MessageResponse:
    service = CampaignService(db)
    try:
        added = await service.add_leads(campaign_id, data.company_ids)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return MessageResponse(message=f"Added {added} leads to campaign")
