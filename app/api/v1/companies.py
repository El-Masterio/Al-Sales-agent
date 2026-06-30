"""
app/api/v1/companies.py
=======================
Company (lead) endpoints: list/search, detail, manual create, research trigger,
and lead-generation kickoff.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, RequireSalesRep
from app.repositories.company_repository import CompanyRepository
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.company import (
    CompanyCreate,
    CompanyDetailResponse,
    CompanyResponse,
    CompanySearchFilters,
    CompanyUpdate,
    ICPCriteria,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=PaginatedResponse[CompanyResponse])
async def list_companies(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = None,
    min_icp_score: int | None = Query(None, ge=0, le=100),
) -> PaginatedResponse[CompanyResponse]:
    repo = CompanyRepository(db)
    filters = CompanySearchFilters(search_query=search, min_icp_score=min_icp_score)
    offset = (page - 1) * page_size
    companies, total = await repo.search(filters, offset=offset, limit=page_size)
    return PaginatedResponse.create(
        items=[CompanyResponse.model_validate(c) for c in companies],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/search", response_model=PaginatedResponse[CompanyResponse])
async def search_companies(
    filters: CompanySearchFilters,
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> PaginatedResponse[CompanyResponse]:
    repo = CompanyRepository(db)
    offset = (page - 1) * page_size
    companies, total = await repo.search(filters, offset=offset, limit=page_size)
    return PaginatedResponse.create(
        items=[CompanyResponse.model_validate(c) for c in companies],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{company_id}", response_model=CompanyDetailResponse)
async def get_company(company_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CompanyDetailResponse:
    repo = CompanyRepository(db)
    company = await repo.get_with_contacts(company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return CompanyDetailResponse.model_validate(company)


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(data: CompanyCreate, db: DbSession, user: RequireSalesRep) -> CompanyResponse:
    repo = CompanyRepository(db)
    import tldextract

    domain = None
    if data.website:
        ext = tldextract.extract(data.website)
        domain = f"{ext.domain}.{ext.suffix}"
        existing = await repo.get_by_domain(domain)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Company with domain {domain} already exists",
            )
    company = await repo.create(**data.model_dump(exclude_none=True), domain=domain)
    return CompanyResponse.model_validate(company)


@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: uuid.UUID, data: CompanyUpdate, db: DbSession, user: RequireSalesRep
) -> CompanyResponse:
    repo = CompanyRepository(db)
    company = await repo.get(company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    updated = await repo.update(company, **data.model_dump(exclude_unset=True, exclude_none=True))
    return CompanyResponse.model_validate(updated)


@router.post("/{company_id}/research", response_model=MessageResponse)
async def trigger_research(company_id: uuid.UUID, db: DbSession, user: RequireSalesRep) -> MessageResponse:
    """Queue an async research task for this company."""
    repo = CompanyRepository(db)
    company = await repo.get(company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    from app.workers.tasks import research_company_task

    research_company_task.delay(str(company_id))
    return MessageResponse(message=f"Research queued for {company.name}")


@router.post("/generate-leads", response_model=MessageResponse)
async def generate_leads(
    criteria: ICPCriteria,
    db: DbSession,
    user: RequireSalesRep,
    max_companies: int = Query(50, ge=1, le=500),
) -> MessageResponse:
    """Kick off an async lead-generation run for the given ICP criteria."""
    from app.workers.tasks import generate_leads_task

    generate_leads_task.delay(criteria.model_dump(), max_companies)
    return MessageResponse(message=f"Lead generation started (up to {max_companies} companies)")
