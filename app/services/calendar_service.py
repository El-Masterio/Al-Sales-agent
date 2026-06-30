"""
app/services/calendar_service.py
================================
Google Calendar integration:
  - OAuth2 authorization URL generation + token exchange
  - Free/busy availability querying
  - Slot generation within working hours
  - Calendar event creation (with Google Meet link)
  - ICS file generation for non-Google attendees

Tokens are stored encrypted on the User row; this service decrypts them
just-in-time to build authorized API clients.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core.config import settings
from app.schemas.meeting import AvailabilitySlot
from app.services.security import decrypt_json, encrypt_json

logger = structlog.get_logger(__name__)


class CalendarService:
    # ── OAuth2 flow ───────────────────────────────────────────────────────────

    def _build_flow(self, state: str | None = None) -> Flow:
        client_config = {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [str(settings.GOOGLE_REDIRECT_URI)],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=settings.GOOGLE_SCOPES,
            state=state,
        )
        flow.redirect_uri = str(settings.GOOGLE_REDIRECT_URI)
        return flow

    def get_authorization_url(self, user_id: uuid.UUID) -> str:
        """Return the Google consent URL. user_id is passed as OAuth state."""
        flow = self._build_flow(state=str(user_id))
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange an authorization code for tokens. Returns token dict."""
        flow = self._build_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }

    def encrypt_token(self, token_data: dict[str, Any]) -> dict[str, Any]:
        """Return an encrypted-at-rest wrapper for the JSONB column."""
        return {"encrypted": encrypt_json(token_data)}

    # ── Credential building ───────────────────────────────────────────────────

    def _credentials_from_stored(self, stored_token: dict[str, Any]) -> Credentials:
        token_data = decrypt_json(stored_token["encrypted"])
        creds = Credentials(
            token=token_data["token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data["token_uri"],
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            scopes=token_data.get("scopes"),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    def _build_calendar_client(self, stored_token: dict[str, Any]):
        creds = self._credentials_from_stored(stored_token)
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # ── Availability ──────────────────────────────────────────────────────────

    def get_busy_blocks(
        self,
        stored_token: dict[str, Any],
        calendar_id: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        service = self._build_calendar_client(stored_token)
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": calendar_id}],
        }
        result = service.freebusy().query(body=body).execute()
        busy = result["calendars"][calendar_id].get("busy", [])
        blocks = []
        for b in busy:
            blocks.append(
                (
                    datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                    datetime.fromisoformat(b["end"].replace("Z", "+00:00")),
                )
            )
        return blocks

    def generate_available_slots(
        self,
        busy_blocks: list[tuple[datetime, datetime]],
        *,
        duration_minutes: int,
        days_ahead: int,
        earliest_hour: int,
        latest_hour: int,
        tz_offset_hours: int = 0,
    ) -> list[AvailabilitySlot]:
        """
        Generate bookable slots within working hours that don't overlap busy
        blocks. Slots are aligned to the duration (e.g. 30-min increments).
        """
        slots: list[AvailabilitySlot] = []
        now = datetime.now(timezone.utc)
        start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        for day_offset in range(1, days_ahead + 1):
            day = start_day + timedelta(days=day_offset)
            # Skip weekends
            if day.weekday() >= 5:
                continue

            slot_start = day.replace(hour=earliest_hour) - timedelta(hours=tz_offset_hours)
            day_end = day.replace(hour=latest_hour) - timedelta(hours=tz_offset_hours)

            while slot_start + timedelta(minutes=duration_minutes) <= day_end:
                slot_end = slot_start + timedelta(minutes=duration_minutes)
                # Skip if overlaps any busy block
                overlaps = any(
                    slot_start < b_end and slot_end > b_start
                    for b_start, b_end in busy_blocks
                )
                if not overlaps and slot_start > now:
                    slots.append(AvailabilitySlot(starts_at=slot_start, ends_at=slot_end))
                slot_start = slot_end

        return slots[:12]   # offer up to 12 slots

    # ── Event creation ────────────────────────────────────────────────────────

    def create_event(
        self,
        stored_token: dict[str, Any],
        calendar_id: str,
        *,
        title: str,
        description: str,
        start: datetime,
        end: datetime,
        attendee_email: str,
        timezone_str: str = "UTC",
        with_meet_link: bool = True,
    ) -> dict[str, Any]:
        service = self._build_calendar_client(stored_token)
        event_body: dict[str, Any] = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone_str},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone_str},
            "attendees": [{"email": attendee_email}],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 30},
                ],
            },
        }
        kwargs: dict[str, Any] = {"calendarId": calendar_id, "body": event_body, "sendUpdates": "all"}
        if with_meet_link:
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            kwargs["conferenceDataVersion"] = 1

        created = service.events().insert(**kwargs).execute()
        meet_link = None
        if "conferenceData" in created:
            for entry in created["conferenceData"].get("entryPoints", []):
                if entry.get("entryPointType") == "video":
                    meet_link = entry.get("uri")
                    break

        return {
            "google_event_id": created["id"],
            "meet_link": meet_link,
            "html_link": created.get("htmlLink"),
        }

    def cancel_event(self, stored_token: dict[str, Any], calendar_id: str, event_id: str) -> None:
        service = self._build_calendar_client(stored_token)
        service.events().delete(
            calendarId=calendar_id, eventId=event_id, sendUpdates="all"
        ).execute()

    # ── ICS generation ────────────────────────────────────────────────────────

    @staticmethod
    def generate_ics(
        *,
        title: str,
        description: str,
        start: datetime,
        end: datetime,
        organizer_email: str,
        attendee_email: str,
        location: str | None = None,
    ) -> str:
        from icalendar import Calendar, Event

        cal = Calendar()
        cal.add("prodid", "-//AI Sales Agent//EN")
        cal.add("version", "2.0")
        cal.add("method", "REQUEST")

        event = Event()
        ics_uid = f"{uuid.uuid4()}@ai-sales-agent"
        event.add("uid", ics_uid)
        event.add("summary", title)
        event.add("description", description)
        event.add("dtstart", start)
        event.add("dtend", end)
        event.add("dtstamp", datetime.now(timezone.utc))
        event.add("organizer", f"mailto:{organizer_email}")
        event.add("attendee", f"mailto:{attendee_email}")
        if location:
            event.add("location", location)

        cal.add_component(event)
        return cal.to_ical().decode("utf-8")


calendar_service = CalendarService()
