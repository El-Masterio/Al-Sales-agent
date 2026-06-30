"""
app/schemas/company.py
======================
Company and Contact request/response schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, HttpUrl

from app.models.base import CompanySize, LeadStatus
from app.schemas.common import TimestampedSchema


# =============================================================================
# Contact
# =============================================================================

class ContactCreate(BaseModel):
    company_id: uuid.UUID
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str | None = None
    title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    is_decision_maker: bool = False
    is_primary_contact: bool = False


class ContactUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    is_decision_maker: bool | None = None
    is_primary_contact: bool | None = None
    notes: str | None = None


class ContactResponse(TimestampedSchema):
    company_id: uuid.UUID
    first_name: str
    last_name: str | None = None
    full_name: str
    title: str | None = None
    seniority: str | None = None
    department: str | None = None
    email: str | None = None
    email_verified: bool
    email_bounce: bool
    phone: str | None = None
    linkedin_url: str | None = None
    is_decision_maker: bool
    is_primary_contact: bool
    unsubscribed: bool


# =============================================================================
# Company
# =============================================================================

class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    website: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    hq_country: str | None = None
    hq_city: str | None = None
    linkedin_url: str | None = None
    crunchbase_url: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    website: str | None = None
    industry: str | None = None
    company_size: CompanySize | None = None
    employee_count: int | None = None
    lead_status: LeadStatus | None = None
    assigned_to_id: uuid.UUID | None = None
    value_proposition: str | None = None


class CompanyResearchResult(BaseModel):
    """Output schema from the AI research pipeline — written back to Company."""

    description: str | None = None
    products_summary: str | None = None
    pain_points: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    recent_news: list[dict[str, Any]] = Field(default_factory=list)
    value_proposition: str | None = None
    icp_score: int = Field(default=0, ge=0, le=100)
    estimated_company_size: CompanySize | None = None
    estimated_employee_count: int | None = None


class CompanyResponse(TimestampedSchema):
    name: str
    website: str | None = None
    domain: str | None = None
    linkedin_url: str | None = None
    crunchbase_url: str | None = None
    industry: str | None = None
    sub_industry: str | None = None
    company_size: CompanySize | None = None
    employee_count: int | None = None
    founded_year: int | None = None
    hq_country: str | None = None
    hq_city: str | None = None
    annual_revenue_usd: int | None = None
    funding_stage: str | None = None
    total_funding_usd: int | None = None
    description: str | None = None
    products_summary: str | None = None
    pain_points: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    recent_news: list[dict[str, Any]] | None = None
    value_proposition: str | None = None
    icp_score: int | None = None
    lead_status: LeadStatus
    assigned_to_id: uuid.UUID | None = None
    last_researched_at: datetime | None = None


class CompanyDetailResponse(CompanyResponse):
    """Full detail view including nested contacts."""

    contacts: list[ContactResponse] = Field(default_factory=list)


class CompanySearchFilters(BaseModel):
    """Filter criteria for the lead list / search endpoint."""

    industries: list[str] | None = None
    company_sizes: list[CompanySize] | None = None
    lead_statuses: list[LeadStatus] | None = None
    tech_stack: list[str] | None = None
    min_icp_score: int | None = Field(default=None, ge=0, le=100)
    assigned_to_id: uuid.UUID | None = None
    search_query: str | None = None   # fuzzy match on name


class ICPCriteria(BaseModel):
    """
    Ideal Customer Profile — used by the lead generation service to
    constrain Google/LinkedIn/Crunchbase searches and score discovered leads.
    """

    industries: list[str] = Field(default_factory=list)
    company_sizes: list[CompanySize] = Field(default_factory=list)
    min_employee_count: int | None = None
    max_employee_count: int | None = None
    target_countries: list[str] = Field(default_factory=list)
    required_tech_stack: list[str] = Field(default_factory=list)
    excluded_tech_stack: list[str] = Field(default_factory=list)
    target_titles: list[str] = Field(default_factory=list)
    funding_stages: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
