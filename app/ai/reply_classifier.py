"""
app/ai/reply_classifier.py
==========================
Classifies inbound replies into actionable categories using the LLM.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.ai.llm_router import LLMResponse, llm_router
from app.ai.prompts import REPLY_CLASSIFICATION_LABELS, reply_classification_prompt
from app.core.config import settings
from app.models.base import ReplyClassification
from app.schemas.email import ReplyClassifyResult

logger = structlog.get_logger(__name__)


class ReplyClassifierAgent:
    async def classify(
        self,
        reply_body: str,
        original_subject: str | None,
        thread_history: list[dict[str, Any]],
    ) -> tuple[ReplyClassifyResult, LLMResponse]:
        system, user = reply_classification_prompt(
            reply_body=reply_body,
            original_email_subject=original_subject,
            thread_history=thread_history,
        )

        response = await llm_router.complete(
            system=system,
            user=user,
            temperature=0.0,    # deterministic classification
            json_mode=True,
        )

        try:
            data = json.loads(response.text)
            classification_str = data.get("classification", "unclassified")
            if classification_str not in REPLY_CLASSIFICATION_LABELS:
                classification_str = "unclassified"

            result = ReplyClassifyResult(
                classification=ReplyClassification(classification_str),
                confidence=float(data.get("confidence", 0.5)),
                sentiment=float(data.get("sentiment", 0.0)),
                summary=data.get("summary", ""),
                suggested_action=data.get("suggested_action", ""),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.error(
                "reply_classifier_invalid_json",
                error=str(exc),
                raw_response=response.text[:500],
            )
            result = ReplyClassifyResult(
                classification=ReplyClassification.UNCLASSIFIED,
                confidence=0.0,
                sentiment=0.0,
                summary="Classification failed — needs manual review.",
                suggested_action="Manually review this reply.",
            )

        logger.info(
            "reply_classified",
            classification=result.classification,
            confidence=result.confidence,
        )

        return result, response


reply_classifier_agent = ReplyClassifierAgent()
