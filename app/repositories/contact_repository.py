"""
app/repositories/contact_repository.py
======================================
Contact-specific data access methods.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.repositories.base import BaseRepository


class ContactRepository(BaseRepository[Contact]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Contact, session)

    async def get_by_email(self, email: str) -> Contact | None:
        stmt = select(Contact).where(Contact.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_company(self, company_id: uuid.UUID) -> list[Contact]:
        stmt = (
            select(Contact)
            .where(Contact.company_id == company_id)
            .order_by(Contact.is_primary_contact.desc(), Contact.is_decision_maker.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_primary_contact(self, company_id: uuid.UUID) -> Contact | None:
        stmt = (
            select(Contact)
            .where(Contact.company_id == company_id)
            .where(Contact.is_primary_contact.is_(True))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_primary_contact(self, company_id: uuid.UUID, contact_id: uuid.UUID) -> None:
        """Unset any existing primary, then set the new one."""
        await self.session.execute(
            update(Contact)
            .where(Contact.company_id == company_id)
            .values(is_primary_contact=False)
        )
        await self.session.execute(
            update(Contact)
            .where(Contact.id == contact_id)
            .values(is_primary_contact=True)
        )
        await self.session.flush()

    async def mark_unsubscribed_by_email(self, email: str) -> Contact | None:
        contact = await self.get_by_email(email)
        if contact:
            contact.mark_unsubscribed()
            await self.session.flush()
        return contact

    async def mark_bounced_by_email(self, email: str) -> Contact | None:
        contact = await self.get_by_email(email)
        if contact:
            contact.mark_bounced()
            await self.session.flush()
        return contact
