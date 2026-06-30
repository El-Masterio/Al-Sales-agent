"""
tests/unit/test_models.py
=========================
Unit tests for ORM model helper methods and computed properties.
These test pure logic and don't require a database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.base import EmailType, LeadStatus, MeetingStatus, ReplyClassification
from app.models.company import Company
from app.models.contact import Contact
from app.models.email import Email
from app.models.meeting import Meeting
from app.models.reply import Reply

pytestmark = pytest.mark.unit


class TestContactHelpers:
    def test_full_name_with_last_name(self):
        c = Contact(first_name="Jane", last_name="Doe")
        assert c.full_name == "Jane Doe"

    def test_full_name_without_last_name(self):
        c = Contact(first_name="Jane")
        assert c.full_name == "Jane"

    def test_display_name_with_title(self):
        c = Contact(first_name="Jane", last_name="Doe", title="CTO")
        assert c.display_name == "Jane Doe, CTO"

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Chief Executive Officer", "c-level"),
            ("VP of Engineering", "vp"),
            ("Director of Sales", "director"),
            ("Engineering Manager", "manager"),
            ("Software Engineer", "ic"),
            ("", "unknown"),
        ],
    )
    def test_infer_seniority(self, title, expected):
        assert Contact.infer_seniority(title) == expected

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Software Engineer", "engineering"),
            ("Head of Marketing", "marketing"),
            ("Sales Director", "sales"),
            ("Product Manager", "product"),
            ("CFO", "finance"),
        ],
    )
    def test_infer_department(self, title, expected):
        assert Contact.infer_department(title) == expected

    def test_is_emailable(self):
        c = Contact(first_name="A", email="a@b.com", email_bounce=False, unsubscribed=False)
        assert c.is_emailable is True

    def test_is_not_emailable_when_bounced(self):
        c = Contact(first_name="A", email="a@b.com", email_bounce=True, unsubscribed=False)
        assert c.is_emailable is False

    def test_mark_unsubscribed(self):
        c = Contact(first_name="A", email="a@b.com")
        c.mark_unsubscribed()
        assert c.unsubscribed is True
        assert c.unsubscribed_at is not None


class TestCompanyHelpers:
    def test_is_contactable_for_new_lead(self):
        company = Company(name="Acme", lead_status=LeadStatus.NEW)
        assert company.is_contactable is True

    def test_is_not_contactable_when_unsubscribed(self):
        company = Company(name="Acme", lead_status=LeadStatus.UNSUBSCRIBED)
        assert company.is_contactable is False

    def test_to_research_context_includes_key_fields(self):
        company = Company(
            name="Acme", website="https://acme.com", industry="SaaS",
            employee_count=100, tech_stack=["React"], recent_news=None,
        )
        ctx = company.to_research_context()
        assert ctx["name"] == "Acme"
        assert ctx["tech_stack"] == ["React"]


class TestEmailHelpers:
    def test_record_open_increments_count(self):
        email = Email(
            company_id=None, email_type=EmailType.INITIAL_OUTREACH,
            subject="x", body_html="x", body_text="x",
            from_email="a@b.com", from_name="A", to_email="c@d.com",
            opened_count=0,
        )
        email.record_open()
        assert email.opened_count == 1
        assert email.first_opened_at is not None

    def test_is_follow_up(self):
        email = Email(
            company_id=None, email_type=EmailType.FOLLOW_UP_1,
            subject="x", body_html="x", body_text="x",
            from_email="a@b.com", from_name="A", to_email="c@d.com",
        )
        assert email.is_follow_up is True


class TestReplyHelpers:
    def test_is_positive_for_interested(self):
        reply = Reply(
            company_id=None, from_email="a@b.com", body_text="yes",
            classification=ReplyClassification.INTERESTED,
        )
        assert reply.is_positive is True

    def test_should_stop_sequence_for_interested(self):
        reply = Reply(
            company_id=None, from_email="a@b.com", body_text="yes",
            classification=ReplyClassification.INTERESTED,
        )
        assert reply.should_stop_sequence is True

    def test_should_not_stop_sequence_for_ooo(self):
        reply = Reply(
            company_id=None, from_email="a@b.com", body_text="ooo",
            classification=ReplyClassification.OUT_OF_OFFICE,
        )
        assert reply.should_stop_sequence is False

    def test_override_classification_takes_precedence(self):
        reply = Reply(
            company_id=None, from_email="a@b.com", body_text="x",
            classification=ReplyClassification.NOT_INTERESTED,
            override_classification=ReplyClassification.INTERESTED,
        )
        assert reply.effective_classification == ReplyClassification.INTERESTED


class TestMeetingHelpers:
    def test_is_upcoming(self):
        meeting = Meeting(
            company_id=None, title="Demo",
            starts_at=datetime.now(timezone.utc) + timedelta(days=1),
            ends_at=datetime.now(timezone.utc) + timedelta(days=1, minutes=30),
            status=MeetingStatus.CONFIRMED,
        )
        assert meeting.is_upcoming is True

    def test_needs_24h_reminder(self):
        meeting = Meeting(
            company_id=None, title="Demo",
            starts_at=datetime.now(timezone.utc) + timedelta(hours=12),
            ends_at=datetime.now(timezone.utc) + timedelta(hours=12, minutes=30),
            status=MeetingStatus.CONFIRMED,
            reminder_24h_sent=False,
        )
        assert meeting.needs_24h_reminder is True
