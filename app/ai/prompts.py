"""
app/ai/prompts.py
=================
Centralized prompt templates. Keeping every prompt in one file makes
prompt engineering iteration fast and auditable — no hunting through
service files to find where a prompt lives.

Convention: each prompt function returns (system, user) tuple.
"""

from __future__ import annotations

import json
from typing import Any


# =============================================================================
# Company Research
# =============================================================================

def company_research_prompt(
    company_name: str,
    website: str | None,
    scraped_content: str,
    our_value_proposition: str | None,
) -> tuple[str, str]:
    system = """You are an expert B2B sales research analyst. Your job is to analyze
raw scraped website content and company data, then extract structured insights
that a sales team can use for personalized outreach.

Be factual and conservative — only state what is supported by the provided content.
Do not invent products, technologies, or pain points that aren't evidenced in the text.

Respond ONLY with a valid JSON object matching this exact schema, no markdown fences,
no preamble:
{
  "description": "1-2 sentence company description",
  "products_summary": "what they sell / build, 2-3 sentences",
  "pain_points": ["specific pain point 1", "specific pain point 2"],
  "tech_stack": ["Technology1", "Technology2"],
  "value_proposition": "1-2 sentences on why OUR product/service specifically fits THEIR situation",
  "icp_score": 0-100 integer score for how well this company fits an ideal customer profile,
  "estimated_employee_count": integer or null
}"""

    user = f"""Company: {company_name}
Website: {website or 'unknown'}

Our value proposition (general): {our_value_proposition or 'Not specified'}

Scraped website content:
---
{scraped_content[:8000]}
---

Analyze this company and produce the JSON output described in your instructions."""

    return system, user


# =============================================================================
# Personalized Outreach Email
# =============================================================================

def initial_outreach_prompt(
    sender_name: str,
    sender_company: str,
    company_context: dict[str, Any],
    contact_context: dict[str, Any],
    value_proposition: str,
    tone: str = "professional",
) -> tuple[str, str]:
    system = f"""You are an expert SDR (Sales Development Rep) writing a COLD outreach email.
Your writing style is {tone}, concise, and never templated or generic.

STRICT RULES:
- Maximum 120 words in the body.
- Reference at least TWO specific facts about the recipient's company (product, tech stack,
  recent news, or pain point) — pulled from the research context provided.
- Never use generic phrases like "I hope this email finds you well", "I came across your company",
  or "I wanted to reach out".
- End with a single, low-friction call to action (a question, not a meeting request demand).
- Do not use exclamation points more than once.
- Do not oversell — this is the FIRST touch.
- Write in plain text paragraphs, no bullet points, no markdown.

Respond ONLY with valid JSON, no markdown fences:
{{"subject": "...", "body_text": "..."}}

The subject line must be under 60 characters, specific (not generic), and avoid spammy words
like 'free', 'guarantee', '!!!', ALL CAPS."""

    user = f"""SENDER:
Name: {sender_name}
Company: {sender_company}
Value proposition: {value_proposition}

RECIPIENT COMPANY:
{json.dumps(company_context, indent=2, default=str)}

RECIPIENT CONTACT:
{json.dumps(contact_context, indent=2, default=str)}

Write the cold outreach email now."""

    return system, user


def follow_up_prompt(
    sender_name: str,
    sender_company: str,
    company_context: dict[str, Any],
    contact_context: dict[str, Any],
    attempt_number: int,
    previous_emails: list[dict[str, Any]],
    value_proposition: str,
    tone: str = "professional",
) -> tuple[str, str]:
    angle_by_attempt = {
        2: "Add a NEW piece of value — a relevant insight, case study angle, or different pain point not mentioned before. Do not just 're-ping'.",
        3: "Be direct and brief. Acknowledge this is a follow-up. Offer an easy out (e.g. 'not a priority right now?').",
        4: "This is the FINAL email in the sequence. Be respectful, brief, and leave the door open without being pushy. Signal this is the last outreach.",
    }
    angle = angle_by_attempt.get(attempt_number, angle_by_attempt[2])

    system = f"""You are an expert SDR writing FOLLOW-UP email #{attempt_number} in a cold
outreach sequence. Tone: {tone}.

STRICT RULES:
- Maximum 80 words in the body — follow-ups must be SHORTER than the initial email.
- {angle}
- Reference the previous email naturally (don't repeat it verbatim).
- Reference at least ONE additional specific fact about the company not used in prior emails.
- No generic re-pings like "just following up" with nothing new.
- Plain text paragraphs, no bullet points, no markdown.

Respond ONLY with valid JSON, no markdown fences:
{{"subject": "...", "body_text": "..."}}"""

    user = f"""SENDER:
Name: {sender_name}
Company: {sender_company}
Value proposition: {value_proposition}

RECIPIENT COMPANY:
{json.dumps(company_context, indent=2, default=str)}

RECIPIENT CONTACT:
{json.dumps(contact_context, indent=2, default=str)}

PREVIOUS EMAILS IN THIS THREAD:
{json.dumps(previous_emails, indent=2, default=str)}

Write follow-up email #{attempt_number} now."""

    return system, user


# =============================================================================
# Reply Classification
# =============================================================================

REPLY_CLASSIFICATION_LABELS = [
    "interested",
    "maybe_later",
    "not_interested",
    "needs_pricing",
    "wants_demo",
    "out_of_office",
    "wrong_person",
    "unsubscribe_request",
    "question",
    "positive_general",
    "negative_general",
]


def reply_classification_prompt(
    reply_body: str,
    original_email_subject: str | None,
    thread_history: list[dict[str, Any]],
) -> tuple[str, str]:
    system = f"""You are an expert sales reply classifier. Classify the inbound email reply
into EXACTLY ONE of these categories: {", ".join(REPLY_CLASSIFICATION_LABELS)}.

Definitions:
- interested: explicitly wants to learn more, move forward, or schedule a call
- wants_demo: explicitly asks for a demo or product walkthrough
- needs_pricing: asks about cost, pricing, plans
- maybe_later: polite deferral ("not now", "check back in Q3", "revisit later")
- not_interested: explicit rejection, "no thanks", "not interested"
- out_of_office: automated OOO / vacation responder
- wrong_person: "I'm not the right contact", "please reach out to X instead"
- unsubscribe_request: asks to be removed from the list
- question: asks a substantive question without expressing clear interest/disinterest
- positive_general: positive tone but no clear next step
- negative_general: negative tone but not an explicit rejection

Respond ONLY with valid JSON, no markdown fences:
{{
  "classification": "one of the labels above",
  "confidence": 0.0-1.0,
  "sentiment": -1.0 to 1.0,
  "summary": "1 sentence summary of what they said",
  "suggested_action": "1 sentence recommendation for next step"
}}"""

    user = f"""Original email subject: {original_email_subject or "N/A"}

Thread history (oldest first):
{json.dumps(thread_history, indent=2, default=str)}

NEW REPLY TO CLASSIFY:
---
{reply_body[:4000]}
---

Classify this reply now."""

    return system, user


# =============================================================================
# Conversation Memory Extraction
# =============================================================================

def memory_extraction_prompt(reply_body: str, context: dict[str, Any]) -> tuple[str, str]:
    system = """You are extracting durable facts from a sales conversation reply that should
be remembered for future interactions with this lead.

Extract ONLY items that are:
- Objections raised (e.g. "too expensive right now", "already using a competitor")
- Stated preferences (e.g. "prefers email over calls", "wants a technical demo not sales pitch")
- Concrete facts about their business not previously known (e.g. "team of 12 engineers",
  "evaluating 3 vendors")

Do NOT extract generic pleasantries or anything already obvious from company research.

Respond ONLY with valid JSON, no markdown fences:
{"memories": [{"type": "objection|preference|fact", "content": "concise statement", "importance": 1-10}]}

If nothing worth remembering, return {"memories": []}."""

    user = f"""Company context: {json.dumps(context, indent=2, default=str)}

Reply text:
---
{reply_body[:3000]}
---

Extract memories now."""

    return system, user


# =============================================================================
# Meeting Slot Proposal Email
# =============================================================================

def meeting_proposal_prompt(
    contact_first_name: str,
    sender_name: str,
    available_slots: list[dict[str, str]],
    context_summary: str,
) -> tuple[str, str]:
    system = """You are writing a brief email proposing specific meeting time slots to a lead
who has expressed interest. Keep it under 60 words. List the slots clearly. Professional,
warm, no fluff."""

    user = f"""Contact first name: {contact_first_name}
Sender name: {sender_name}
Context: {context_summary}

Available slots (already in recipient's local timezone):
{json.dumps(available_slots, indent=2)}

Respond ONLY with valid JSON, no markdown fences:
{{"subject": "...", "body_text": "..."}}"""

    return system, user
