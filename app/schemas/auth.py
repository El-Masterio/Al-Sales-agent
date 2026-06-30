"""
app/schemas/auth.py
===================
Authentication and user-related request/response schemas.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.base import UserRole
from app.schemas.common import TimestampedSchema


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.SALES_REP


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    avatar_url: str | None = None
    timezone: str | None = None
    is_active: bool | None = None


class UserResponse(TimestampedSchema):
    email: str
    full_name: str
    role: UserRole
    avatar_url: str | None = None
    timezone: str
    is_active: bool
    has_calendar_connected: bool = False
    last_login_at: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenPayload(BaseModel):
    sub: str          # user id
    role: str
    exp: int
    type: str          # "access" | "refresh"


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
