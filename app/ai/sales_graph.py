"""
app/ai/sales_graph.py
=====================
LangGraph state machine orchestrating the autonomous lead lifecycle:

    research → generate_outreach → (send handled by worker) → classify_reply
        → extract_memory → decide_next_action → (book_meeting | follow_up | stop)

This graph is invoked by Celery tasks at each lifecycle transition rather
than run end-to-end synchronously — each node corresponds to a discrete,
auditable step that can be retried independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.ai.memory_agent import memory_agent
from app.ai.outreach_agent import outreach_agent
from app.ai.reply_classifier import reply_classifier_agent
from app.ai.research_agent import research_agent
from app.models.base import ReplyClassification

logger = structlog.get_logger(__name__)


class SalesGraphState(TypedDict, total=False):
    """Shared state passed between graph nodes."""

    # Input
    company_id: str
    company_name: str
    website: str | None
    scraped_content: str | None
    sender_name: str
    sender_company: str
    value_proposition: str
    tone: str
    company_context: dict[str, Any]
    contact_context: dict[str, Any]
    attempt_number: int
    previous_emails: list[dict[str, Any]]

    # Reply handling input
    reply_body: str | None
    reply_subject: str | None
    thread_history: list[dict[str, Any]]

    # Outputs
    research_result: dict[str, Any] | None
    generated_email: dict[str, str] | None
    classification_result: dict[str, Any] | None
    extracted_memories: list[dict[str, Any]]
    next_action: str | None
    error: str | None


# =============================================================================
# Node implementations
# =============================================================================

async def node_research_company(state: SalesGraphState) -> SalesGraphState:
    """Analyze scraped content and produce structured research."""
    if not state.get("scraped_content"):
        state["error"] = "No scraped content available for research"
        return state

    try:
        result, _ = await research_agent.research_company(
            company_name=state["company_name"],
            website=state.get("website"),
            scraped_content=state["scraped_content"],
            our_value_proposition=state.get("value_proposition"),
        )
        state["research_result"] = result.model_dump()
    except Exception as exc:
        logger.error("graph_research_failed", error=str(exc))
        state["error"] = f"Research failed: {exc}"

    return state


async def node_generate_outreach(state: SalesGraphState) -> SalesGraphState:
    """Generate the initial outreach or follow-up email."""
    attempt = state.get("attempt_number", 1)

    try:
        if attempt == 1:
            email, _ = await outreach_agent.generate_initial_email(
                sender_name=state["sender_name"],
                sender_company=state["sender_company"],
                company_context=state["company_context"],
                contact_context=state["contact_context"],
                value_proposition=state["value_proposition"],
                tone=state.get("tone", "professional"),
            )
        else:
            email, _ = await outreach_agent.generate_follow_up_email(
                sender_name=state["sender_name"],
                sender_company=state["sender_company"],
                company_context=state["company_context"],
                contact_context=state["contact_context"],
                attempt_number=attempt,
                previous_emails=state.get("previous_emails", []),
                value_proposition=state["value_proposition"],
                tone=state.get("tone", "professional"),
            )
        state["generated_email"] = email
    except Exception as exc:
        logger.error("graph_outreach_generation_failed", error=str(exc))
        state["error"] = f"Outreach generation failed: {exc}"

    return state


async def node_classify_reply(state: SalesGraphState) -> SalesGraphState:
    """Classify an inbound reply."""
    if not state.get("reply_body"):
        state["error"] = "No reply body to classify"
        return state

    try:
        result, _ = await reply_classifier_agent.classify(
            reply_body=state["reply_body"],
            original_subject=state.get("reply_subject"),
            thread_history=state.get("thread_history", []),
        )
        state["classification_result"] = result.model_dump()
    except Exception as exc:
        logger.error("graph_classification_failed", error=str(exc))
        state["error"] = f"Classification failed: {exc}"

    return state


async def node_extract_memory(state: SalesGraphState) -> SalesGraphState:
    """Extract durable memories from the reply."""
    if not state.get("reply_body"):
        state["extracted_memories"] = []
        return state

    try:
        memories = await memory_agent.extract_memories(
            reply_body=state["reply_body"],
            context=state.get("company_context", {}),
        )
        state["extracted_memories"] = memories
    except Exception as exc:
        logger.error("graph_memory_extraction_failed", error=str(exc))
        state["extracted_memories"] = []

    return state


async def node_decide_next_action(state: SalesGraphState) -> SalesGraphState:
    """
    Decide what should happen next based on classification result.
    This is the routing/decision node — actual side effects (booking,
    scheduling follow-ups) are executed by the calling Celery task,
    not within the graph itself.
    """
    classification_data = state.get("classification_result")
    if not classification_data:
        state["next_action"] = "no_action"
        return state

    classification = classification_data.get("classification")

    action_map = {
        ReplyClassification.INTERESTED.value: "propose_meeting",
        ReplyClassification.WANTS_DEMO.value: "propose_meeting",
        ReplyClassification.NEEDS_PRICING.value: "send_pricing_then_propose_meeting",
        ReplyClassification.MAYBE_LATER.value: "snooze_lead",
        ReplyClassification.NOT_INTERESTED.value: "mark_not_interested",
        ReplyClassification.UNSUBSCRIBE.value: "unsubscribe_contact",
        ReplyClassification.OUT_OF_OFFICE.value: "continue_sequence",
        ReplyClassification.WRONG_PERSON.value: "flag_for_human",
        ReplyClassification.QUESTION.value: "flag_for_human",
        ReplyClassification.POSITIVE_GENERAL.value: "flag_for_human",
        ReplyClassification.NEGATIVE_GENERAL.value: "flag_for_human",
    }

    state["next_action"] = action_map.get(classification, "flag_for_human")
    return state


# =============================================================================
# Graph construction
# =============================================================================

def build_research_graph() -> StateGraph:
    """Single-node graph: research only. Used by the lead research task."""
    graph = StateGraph(SalesGraphState)
    graph.add_node("research", node_research_company)
    graph.set_entry_point("research")
    graph.add_edge("research", END)
    return graph.compile()


def build_outreach_graph() -> StateGraph:
    """Single-node graph: generate outreach email. Used by the outreach task."""
    graph = StateGraph(SalesGraphState)
    graph.add_node("generate", node_generate_outreach)
    graph.set_entry_point("generate")
    graph.add_edge("generate", END)
    return graph.compile()


def build_reply_handling_graph() -> StateGraph:
    """
    Full reply-handling pipeline: classify → extract memory → decide action.
    Used by the inbound webhook processing task.
    """
    graph = StateGraph(SalesGraphState)
    graph.add_node("classify", node_classify_reply)
    graph.add_node("extract_memory", node_extract_memory)
    graph.add_node("decide", node_decide_next_action)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "extract_memory")
    graph.add_edge("extract_memory", "decide")
    graph.add_edge("decide", END)

    return graph.compile()


# Compiled graph singletons — compilation is relatively expensive, do it once
research_graph = build_research_graph()
outreach_graph = build_outreach_graph()
reply_handling_graph = build_reply_handling_graph()
