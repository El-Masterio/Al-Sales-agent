"""
tests/unit/test_ai_agents.py
============================
Tests for AI agents using the mocked LLM router (no real API calls).
"""

from __future__ import annotations

import pytest

from app.ai.outreach_agent import outreach_agent

pytestmark = pytest.mark.unit


class TestOutreachAgent:
    async def test_generate_initial_email(self, mock_llm):
        email, response = await outreach_agent.generate_initial_email(
            sender_name="Alex",
            sender_company="OurCo",
            company_context={"name": "Acme", "tech_stack": ["React"]},
            contact_context={"first_name": "Jane", "title": "CTO"},
            value_proposition="We reduce churn",
        )
        assert "subject" in email
        assert "body_text" in email
        assert response.prompt_tokens == 100

    def test_email_type_for_attempt(self):
        from app.models.base import EmailType

        assert outreach_agent.email_type_for_attempt(1) == EmailType.INITIAL_OUTREACH
        assert outreach_agent.email_type_for_attempt(2) == EmailType.FOLLOW_UP_1
        assert outreach_agent.email_type_for_attempt(4) == EmailType.FOLLOW_UP_3

    def test_render_html_wraps_paragraphs(self):
        html = outreach_agent.render_html("Para one.\n\nPara two.", "Alex", "OurCo")
        assert "<p>Para one.</p>" in html
        assert "<p>Para two.</p>" in html
        assert "Alex" in html


class TestReplyClassifier:
    async def test_classify_returns_result(self, monkeypatch):
        from unittest.mock import AsyncMock

        from app.ai import reply_classifier as rc_module
        from app.ai.llm_router import LLMResponse

        async def fake_complete(*args, **kwargs):
            return LLMResponse(
                text='{"classification": "interested", "confidence": 0.9, '
                '"sentiment": 0.8, "summary": "wants to learn more", '
                '"suggested_action": "book a meeting"}',
                model="mock", provider="openai",
                prompt_tokens=50, completion_tokens=20, generation_ms=10,
            )

        monkeypatch.setattr(
            rc_module.llm_router, "complete", AsyncMock(side_effect=fake_complete)
        )

        result, _ = await rc_module.reply_classifier_agent.classify(
            reply_body="I'm interested, tell me more",
            original_subject="Intro",
            thread_history=[],
        )
        assert result.classification.value == "interested"
        assert result.confidence == 0.9
