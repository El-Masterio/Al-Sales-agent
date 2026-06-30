"""
app/repositories/user_repository.py
===================================
User data access methods.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_reps(self) -> list[User]:
        from app.models.base import UserRole

        stmt = select(User).where(
            User.is_active.is_(True),
            User.role.in_([UserRole.SALES_REP, UserRole.ADMIN]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_with_calendar_connected(self) -> list[User]:
        stmt = select(User).where(
            User.is_active.is_(True),
            User.google_calendar_token.is_not(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
