"""
app/ai/memory_agent.py
======================
Extracts durable memory items (objections, preferences, facts) from reply
text and prepares them for storage with embeddings in ConversationMemory.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from app.ai.llm_router import llm_router
from app.ai.prompts import memory_extraction_prompt

logger = structlog.get_logger(__name__)


class MemoryAgent:
    async def extract_memories(
        self,
        reply_body: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Returns a list of {type, content, importance} dicts ready to be
        embedded and persisted as ConversationMemory rows.
        """
        system, user = memory_extraction_prompt(reply_body, context)

        response = await llm_router.complete(
            system=system,
            user=user,
            temperature=0.1,
            json_mode=True,
        )

        try:
            data = json.loads(response.text)
            memories = data.get("memories", [])
            valid = [
                m for m in memories
                if isinstance(m, dict) and "type" in m and "content" in m
            ]
            return valid
        except json.JSONDecodeError:
            logger.error("memory_agent_invalid_json", raw_response=response.text[:500])
            return []

    async def embed_memories(self, memories: list[dict[str, Any]]) -> list[list[float]]:
        """Batch-embed memory content strings for pgvector storage."""
        texts = [m["content"] for m in memories]
        return await llm_router.embed_batch(texts)

    async def embed_query(self, query: str) -> list[float]:
        """Embed a query string for semantic similarity search."""
        return await llm_router.embed(query)


memory_agent = MemoryAgent()
