"""Google OAuth, Gmail, and Calendar side effects for approved proposals."""

from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .schemas import CalendarEventProposal, EmailDraftProposal

# ``users.getProfile`` below is used to ensure the token belongs to the configured
# sender.  ``gmail.send`` alone cannot call that endpoint; ``gmail.metadata`` is
# the least-privileged Gmail scope accepted by it (it does not grant message-body
# access).
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.metadata",
]
SENDER_EMAIL = "nayakswadesh@gmail.com"
TIMEZONE = "Asia/Kolkata"
IST = timezone(timedelta(hours=5, minutes=30))


class GoogleConnectionError(RuntimeError):
    """Raised when an approved operation has no authorized Google account."""


def _token_path() -> Path:
    return Path(os.getenv("GOOGLE_TOKEN_FILE", "google-token.json"))


def _client_secret_path() -> Path:
    return Path(os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "google-client-secret.json"))


def connect_google_account() -> str:
    """Run a browser OAuth flow and save a refreshable token for the bot process."""
    secrets = _client_secret_path()
    if not secrets.exists():
        raise GoogleConnectionError(f"Google OAuth client file not found: {secrets}. Set GOOGLE_CLIENT_SECRETS_FILE first.")
    credentials = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES).run_local_server(port=0)
    _token_path().write_text(credentials.to_json(), encoding="utf-8")
    return _authorized_email(credentials)


def _credentials() -> Credentials:
    token = _token_path()
    if not token.exists():
        raise GoogleConnectionError("Google account is not connected. Run `python -m src.connect_google` on this machine.")
    credentials = Credentials.from_authorized_user_file(str(token), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise GoogleConnectionError("Google authorization has expired. Reconnect with `python -m src.connect_google`.")
    authorized_email = _authorized_email(credentials)
    if authorized_email.lower() != SENDER_EMAIL:
        raise GoogleConnectionError(
            f"Connected as {authorized_email}, but this bot is configured to send as {SENDER_EMAIL}. Reconnect with the correct account."
        )
    return credentials


def _authorized_email(credentials: Credentials) -> str:
    return str(build("gmail", "v1", credentials=credentials, cache_discovery=False).users().getProfile(userId="me").execute()["emailAddress"])


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed


def send_email(draft: EmailDraftProposal) -> str:
    recipients = [address.strip() for address in draft.to if "@" in address]
    if not recipients:
        raise ValueError("The email draft has no valid stakeholder email addresses; it was not sent.")
    message = EmailMessage()
    message["To"] = ", ".join(recipients)
    message["From"] = SENDER_EMAIL
    message["Subject"] = draft.subject
    message.set_content(draft.body.replace("**", ""))
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result = build("gmail", "v1", credentials=_credentials(), cache_discovery=False).users().messages().send(userId="me", body={"raw": encoded}).execute()
    return f"Email sent from {SENDER_EMAIL} to {', '.join(recipients)} (id: {result['id']})"


def book_calendar(event: CalendarEventProposal) -> str:
    if event.start_time == "TBD" or event.end_time == "TBD":
        raise ValueError("The calendar event has no confirmed start and end time; it was not created.")
    start, end = _parse_datetime(event.start_time), _parse_datetime(event.end_time)
    body: dict[str, Any] = {
        "summary": event.title, "description": event.description.replace("**", ""),
        "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
        "attendees": [{"email": address} for address in event.attendees if "@" in address],
    }
    result = build("calendar", "v3", credentials=_credentials(), cache_discovery=False).events().insert(calendarId="primary", body=body, sendUpdates="all").execute()
    return f"Calendar invite created by {SENDER_EMAIL}: {result.get('htmlLink', event.title)}"
