"""
tests/conftest.py
=================
Shared pytest fixtures: async DB session against a test database,
an httpx AsyncClient bound to the FastAPI app, auth helpers, and a
mocked LLM router so tests never hit real AI providers.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.llm_router import LLMResponse
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base, UserRole
from app.models.user import User
from app.services.security import create_access_token, hash_password

# Use a dedicated test database
TEST_DATABASE_URL = settings.database_url_str.replace("/sales_agent", "/sales_agent_test")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        # pgvector + uuid extensions must exist for the test DB too
        from sqlalchemy import text

        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector"'))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session wrapped in a rolled-back transaction for isolation."""
    connection = await engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
    session = session_factory()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient bound to the app, with get_db overridden to use the test session."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session) -> User:
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Test User",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(test_user.id, test_user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_llm(monkeypatch):
    """Patch the LLM router so no real AI calls are made."""

    async def _fake_complete(*args, **kwargs):
        return LLMResponse(
            text='{"subject": "Test Subject", "body_text": "Test body referencing your product."}',
            model="mock-model",
            provider="openai",
            prompt_tokens=100,
            completion_tokens=50,
            generation_ms=42,
        )

    async def _fake_embed(*args, **kwargs):
        return [0.0] * 1536

    async def _fake_embed_batch(texts):
        return [[0.0] * 1536 for _ in texts]

    from app.ai import llm_router as llm_module

    monkeypatch.setattr(llm_module.llm_router, "complete", AsyncMock(side_effect=_fake_complete))
    monkeypatch.setattr(llm_module.llm_router, "embed", AsyncMock(side_effect=_fake_embed))
    monkeypatch.setattr(llm_module.llm_router, "embed_batch", AsyncMock(side_effect=_fake_embed_batch))
    return llm_module.llm_router
