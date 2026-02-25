"""
Microsoft Graph API Integration — connects Nellie to Outlook, Calendar, and OneDrive.

Provides:
- Email ingestion (read recent emails, search, send drafts)
- Calendar queries (today's events, upcoming meetings)
- OneDrive file access (read documents for knowledge extraction)

Authentication: Uses OAuth2 with device code flow or client credentials.
Credentials stored at ~/.nellie/config/microsoft_graph.json

The integration exposes both:
1. Direct Python API (for graph builder and scheduler)
2. Nanobot tools (for agents to query during execution)
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

NELLIE_HOME = Path(os.getenv("NELLIE_HOME", str(Path.home() / ".nellie")))
CRED_FILE = NELLIE_HOME / "config" / "microsoft_graph.json"
TOKEN_FILE = NELLIE_HOME / "config" / ".ms_graph_token.json"

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Default scopes for Nellie's Microsoft Graph access
DEFAULT_SCOPES = [
    "User.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "Calendars.ReadWrite",
    "Contacts.Read",
    "Files.Read",
    "Tasks.ReadWrite",
]


class MicrosoftGraphCredentials:
    """Manages OAuth2 credentials and token refresh for Microsoft Graph."""

    def __init__(self):
        self.client_id: str = ""
        self.client_secret: str = ""
        self.tenant_id: str = "common"
        self.access_token: str = ""
        self.refresh_token: str = ""
        self.token_expires: float = 0
        self._loaded = False

    def load(self) -> bool:
        """Load credentials from config file."""
        if not CRED_FILE.exists():
            log.info("ms_graph_no_credentials", path=str(CRED_FILE))
            return False

        try:
            data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
            self.client_id = data.get("client_id", "")
            self.client_secret = data.get("client_secret", "")
            self.tenant_id = data.get("tenant_id", "common")
            self._loaded = True

            # Load cached token if available
            if TOKEN_FILE.exists():
                token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                self.access_token = token_data.get("access_token", "")
                self.refresh_token = token_data.get("refresh_token", "")
                self.token_expires = token_data.get("expires_at", 0)

            return bool(self.client_id)
        except Exception as e:
            log.error("ms_graph_cred_load_error", error=str(e))
            return False

    def save_token(self, token_response: dict) -> None:
        """Save token response to disk."""
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.access_token = token_response.get("access_token", "")
        self.refresh_token = token_response.get("refresh_token", self.refresh_token)
        self.token_expires = time.time() + token_response.get("expires_in", 3600) - 60
        TOKEN_FILE.write_text(json.dumps({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.token_expires,
        }), encoding="utf-8")

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id)

    @property
    def is_token_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.token_expires


class MicrosoftGraphClient:
    """
    Microsoft Graph API client for Nellie.

    Handles authentication, token refresh, and provides methods for
    mail, calendar, and file operations.
    """

    def __init__(self):
        self.creds = MicrosoftGraphCredentials()
        self._client: httpx.AsyncClient | None = None

    async def initialize(self) -> bool:
        """Initialize the client — load credentials, refresh token if needed."""
        if not self.creds.load():
            return False

        if not self.creds.is_token_valid and self.creds.refresh_token:
            await self._refresh_token()

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=30, pool=30),
            headers=self._auth_headers(),
        )
        return self.creds.is_token_valid

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.creds.access_token}",
            "Content-Type": "application/json",
        }

    async def _refresh_token(self) -> bool:
        """Refresh the OAuth2 access token."""
        if not self.creds.refresh_token:
            return False

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{self.creds.tenant_id}/oauth2/v2.0/token",
                    data={
                        "client_id": self.creds.client_id,
                        "client_secret": self.creds.client_secret,
                        "refresh_token": self.creds.refresh_token,
                        "grant_type": "refresh_token",
                        "scope": " ".join(DEFAULT_SCOPES),
                    },
                )
                if resp.status_code == 200:
                    self.creds.save_token(resp.json())
                    log.info("ms_graph_token_refreshed")
                    return True
                else:
                    log.error("ms_graph_token_refresh_failed", status=resp.status_code)
                    return False
            except Exception as e:
                log.error("ms_graph_token_refresh_error", error=str(e))
                return False

    async def _ensure_token(self) -> bool:
        """Ensure we have a valid token before making requests."""
        if self.creds.is_token_valid:
            return True
        if self.creds.refresh_token:
            refreshed = await self._refresh_token()
            if refreshed and self._client:
                self._client.headers.update(self._auth_headers())
            return refreshed
        return False

    async def _get(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Make a GET request to Microsoft Graph API with 429 retry."""
        if not await self._ensure_token() or not self._client:
            return None

        url = endpoint if endpoint.startswith("https://") else f"{GRAPH_BASE}{endpoint}"
        retries = 0
        max_retries = 3

        while retries <= max_retries:
            try:
                resp = await self._client.get(url, params=params if retries == 0 else None)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    # Rate limited — respect Retry-After header
                    retry_after = int(resp.headers.get("Retry-After", "5"))
                    log.warning("ms_graph_rate_limited", endpoint=endpoint, retry_after=retry_after)
                    await asyncio.sleep(retry_after)
                    retries += 1
                    continue
                elif resp.status_code == 401:
                    if await self._refresh_token():
                        self._client.headers.update(self._auth_headers())
                        retries += 1
                        continue
                log.warning("ms_graph_get_error", endpoint=endpoint, status=resp.status_code)
                return None
            except Exception as e:
                log.error("ms_graph_request_error", endpoint=endpoint, error=str(e))
                return None
        return None

    async def _paginate(
        self, endpoint: str, params: dict | None = None, max_pages: int = 5,
    ) -> list[dict]:
        """Auto-paginate through a Graph API collection following @odata.nextLink."""
        results: list[dict] = []
        data = await self._get(endpoint, params)
        if not data:
            return results

        results.extend(data.get("value", []))
        next_link = data.get("@odata.nextLink")
        page = 1

        while next_link and page < max_pages:
            data = await self._get(next_link)
            if not data:
                break
            results.extend(data.get("value", []))
            next_link = data.get("@odata.nextLink")
            page += 1

        return results

    async def _post(self, endpoint: str, data: dict) -> dict | None:
        """Make a POST request to Microsoft Graph API."""
        if not await self._ensure_token() or not self._client:
            return None
        try:
            resp = await self._client.post(f"{GRAPH_BASE}{endpoint}", json=data)
            if resp.status_code in (200, 201, 202):
                return resp.json() if resp.text else {"status": "ok"}
            log.warning("ms_graph_post_error", endpoint=endpoint, status=resp.status_code)
            return None
        except Exception as e:
            log.error("ms_graph_request_error", endpoint=endpoint, error=str(e))
            return None

    # ── Mail ─────────────────────────────────────────────────────────────

    async def get_recent_emails(self, count: int = 20, folder: str = "inbox") -> list[dict]:
        """Get recent emails from the specified folder."""
        data = await self._get(
            f"/me/mailFolders/{folder}/messages",
            params={
                "$top": str(count),
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,importance",
            },
        )
        if not data:
            return []
        return [
            {
                "id": msg["id"],
                "subject": msg.get("subject", ""),
                "from": msg.get("from", {}).get("emailAddress", {}).get("name", ""),
                "from_email": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "to": [r.get("emailAddress", {}).get("name", "") for r in msg.get("toRecipients", [])],
                "received": msg.get("receivedDateTime", ""),
                "preview": msg.get("bodyPreview", ""),
                "is_read": msg.get("isRead", False),
                "importance": msg.get("importance", "normal"),
            }
            for msg in data.get("value", [])
        ]

    async def get_email_body(self, message_id: str) -> dict | None:
        """Get the full body of an email."""
        data = await self._get(
            f"/me/messages/{message_id}",
            params={"$select": "id,subject,from,toRecipients,body,receivedDateTime,conversationId"},
        )
        if not data:
            return None
        return {
            "id": data["id"],
            "subject": data.get("subject", ""),
            "from": data.get("from", {}).get("emailAddress", {}).get("name", ""),
            "body": data.get("body", {}).get("content", ""),
            "body_type": data.get("body", {}).get("contentType", "text"),
            "received": data.get("receivedDateTime", ""),
            "conversation_id": data.get("conversationId", ""),
        }

    async def search_emails(self, query: str, count: int = 10) -> list[dict]:
        """Search emails by subject, body, or sender."""
        data = await self._get(
            "/me/messages",
            params={
                "$search": f'"{query}"',
                "$top": str(count),
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
            },
        )
        if not data:
            return []
        return [
            {
                "id": msg["id"],
                "subject": msg.get("subject", ""),
                "from": msg.get("from", {}).get("emailAddress", {}).get("name", ""),
                "received": msg.get("receivedDateTime", ""),
                "preview": msg.get("bodyPreview", ""),
            }
            for msg in data.get("value", [])
        ]

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
        save_to_sent: bool = True,
    ) -> bool:
        """Send an email."""
        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": [
                    {"emailAddress": {"address": addr}} for addr in to
                ],
            },
            "saveToSentItems": save_to_sent,
        }
        result = await self._post("/me/sendMail", message)
        return result is not None

    async def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
    ) -> dict | None:
        """Create an email draft (not sent)."""
        draft = {
            "subject": subject,
            "body": {"contentType": body_type, "content": body},
            "toRecipients": [
                {"emailAddress": {"address": addr}} for addr in to
            ],
        }
        return await self._post("/me/messages", draft)

    # ── Calendar ─────────────────────────────────────────────────────────

    async def get_today_events(self) -> list[dict]:
        """Get today's calendar events."""
        now = datetime.utcnow()
        start = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
        end = now.replace(hour=23, minute=59, second=59).isoformat() + "Z"

        data = await self._get(
            "/me/calendarview",
            params={
                "startDateTime": start,
                "endDateTime": end,
                "$select": "id,subject,start,end,location,organizer,attendees,isAllDay",
                "$orderby": "start/dateTime",
            },
        )
        if not data:
            return []
        return [
            {
                "id": evt["id"],
                "subject": evt.get("subject", ""),
                "start": evt.get("start", {}).get("dateTime", ""),
                "end": evt.get("end", {}).get("dateTime", ""),
                "location": evt.get("location", {}).get("displayName", ""),
                "organizer": evt.get("organizer", {}).get("emailAddress", {}).get("name", ""),
                "attendees": [
                    a.get("emailAddress", {}).get("name", "")
                    for a in evt.get("attendees", [])
                ],
                "is_all_day": evt.get("isAllDay", False),
            }
            for evt in data.get("value", [])
        ]

    async def get_upcoming_events(self, days: int = 7) -> list[dict]:
        """Get upcoming calendar events for the next N days."""
        now = datetime.utcnow()
        start = now.isoformat() + "Z"
        end = (now + timedelta(days=days)).isoformat() + "Z"

        data = await self._get(
            "/me/calendarview",
            params={
                "startDateTime": start,
                "endDateTime": end,
                "$select": "id,subject,start,end,location,organizer",
                "$orderby": "start/dateTime",
                "$top": "50",
            },
        )
        if not data:
            return []
        return [
            {
                "id": evt["id"],
                "subject": evt.get("subject", ""),
                "start": evt.get("start", {}).get("dateTime", ""),
                "end": evt.get("end", {}).get("dateTime", ""),
                "organizer": evt.get("organizer", {}).get("emailAddress", {}).get("name", ""),
            }
            for evt in data.get("value", [])
        ]

    # ── Contacts ──────────────────────────────────────────────────────────

    async def get_contacts(self, count: int = 100) -> list[dict]:
        """Get Outlook contacts (structured data — no LLM needed for vault merge)."""
        results = await self._paginate(
            "/me/contacts",
            params={
                "$top": str(min(count, 100)),
                "$select": "id,displayName,givenName,surname,emailAddresses,businessPhones,mobilePhone,companyName,jobTitle,department",
                "$orderby": "displayName",
            },
            max_pages=max(1, count // 100),
        )
        return [
            {
                "id": c.get("id", ""),
                "name": c.get("displayName", ""),
                "email": (c.get("emailAddresses") or [{}])[0].get("address", "") if c.get("emailAddresses") else "",
                "company": c.get("companyName", ""),
                "title": c.get("jobTitle", ""),
                "department": c.get("department", ""),
                "phone": (c.get("businessPhones") or [""])[0] or c.get("mobilePhone", ""),
            }
            for c in results if c.get("displayName")
        ]

    async def search_contacts(self, query: str) -> list[dict]:
        """Search contacts by name prefix."""
        safe_query = query.replace("'", "''")
        results = await self._paginate(
            "/me/contacts",
            params={
                "$filter": f"startswith(displayName,'{safe_query}')",
                "$top": "25",
                "$select": "id,displayName,emailAddresses,companyName,jobTitle",
            },
        )
        return [
            {
                "name": c.get("displayName", ""),
                "email": (c.get("emailAddresses") or [{}])[0].get("address", "") if c.get("emailAddresses") else "",
                "company": c.get("companyName", ""),
                "title": c.get("jobTitle", ""),
            }
            for c in results if c.get("displayName")
        ]

    # ── Tasks (Microsoft To Do) ──────────────────────────────────────────

    async def get_task_lists(self) -> list[dict]:
        """Get all To Do task lists."""
        results = await self._paginate("/me/todo/lists")
        return [
            {"id": tl.get("id", ""), "name": tl.get("displayName", "")}
            for tl in results
        ]

    async def get_tasks(
        self, status: str = "all", count: int = 50, list_id: str | None = None,
    ) -> list[dict]:
        """Get tasks from Microsoft To Do. Status: notStarted, inProgress, completed, all."""
        if list_id:
            params: dict[str, str] = {"$top": str(count)}
            if status != "all":
                params["$filter"] = f"status eq '{status}'"
            results = await self._paginate(f"/me/todo/lists/{list_id}/tasks", params)
        else:
            # Fetch from all lists
            lists = await self.get_task_lists()
            results = []
            for tl in lists:
                params = {"$top": str(count)}
                if status != "all":
                    params["$filter"] = f"status eq '{status}'"
                try:
                    tasks = await self._paginate(f"/me/todo/lists/{tl['id']}/tasks", params)
                    for t in tasks:
                        t["_list_name"] = tl["name"]
                    results.extend(tasks)
                except Exception:
                    pass

        return [
            {
                "id": t.get("id", ""),
                "title": t.get("title", ""),
                "status": t.get("status", ""),
                "importance": t.get("importance", "normal"),
                "due": (t.get("dueDateTime") or {}).get("dateTime", "")[:10] if t.get("dueDateTime") else "",
                "list": t.get("_list_name", ""),
            }
            for t in results[:count] if t.get("title")
        ]

    async def create_task(
        self, title: str, list_id: str | None = None,
        body: str = "", due_date: str = "", importance: str = "normal",
    ) -> dict | None:
        """Create a task in Microsoft To Do."""
        if not list_id:
            lists = await self.get_task_lists()
            if not lists:
                return None
            list_id = lists[0]["id"]

        task_data: dict[str, Any] = {"title": title, "importance": importance}
        if body:
            task_data["body"] = {"content": body, "contentType": "text"}
        if due_date:
            task_data["dueDateTime"] = {"dateTime": due_date, "timeZone": "America/Chicago"}

        return await self._post(f"/me/todo/lists/{list_id}/tasks", task_data)

    # ── Composite Queries ─────────────────────────────────────────────────

    async def get_daily_digest(self) -> dict:
        """Daily digest: unread emails + today's events + pending tasks in parallel."""
        emails_task = asyncio.create_task(self.get_recent_emails(count=50, folder="inbox"))
        events_task = asyncio.create_task(self.get_today_events())
        tasks_task = asyncio.create_task(self.get_tasks(status="notStarted", count=25))

        emails = await emails_task
        events = await events_task
        tasks = await tasks_task

        # Filter to unread only
        unread = [e for e in emails if not e.get("is_read")]

        return {
            "summary": f"{len(unread)} unread emails, {len(events)} events today, {len(tasks)} pending tasks",
            "unread_emails": unread[:15],
            "today_events": events,
            "pending_tasks": tasks,
        }

    async def get_person_context(self, name_or_email: str) -> dict:
        """Gather all context about a person: contact + emails + shared events."""
        contacts_task = asyncio.create_task(self.search_contacts(name_or_email))
        emails_task = asyncio.create_task(self.search_emails(name_or_email, count=10))
        events_task = asyncio.create_task(self.get_upcoming_events(days=30))

        contacts = await contacts_task
        emails = await emails_task
        events = await events_task

        contact = contacts[0] if contacts else None

        # Filter events to those with the person as attendee
        search_lower = name_or_email.lower()
        shared = [
            e for e in events
            if any(search_lower in a.lower() for a in e.get("attendees", []))
            or search_lower in e.get("organizer", "").lower()
        ]

        return {
            "contact": contact,
            "recent_emails": emails[:5],
            "shared_events": shared[:5],
        }

    # ── User Profile ─────────────────────────────────────────────────────

    async def get_me(self) -> dict | None:
        """Get the authenticated user's profile."""
        return await self._get("/me")

    # ── Status ───────────────────────────────────────────────────────────

    async def get_status(self) -> dict:
        """Get integration status."""
        return {
            "configured": self.creds.is_configured,
            "authenticated": self.creds.is_token_valid,
            "token_expires_in": max(0, int(self.creds.token_expires - time.time())),
            "credentials_path": str(CRED_FILE),
        }

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton
ms_graph = MicrosoftGraphClient()


def create_credentials_template() -> None:
    """Create a template credentials file for Microsoft Graph."""
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CRED_FILE.exists():
        print(f"Credentials file already exists: {CRED_FILE}")
        return

    template = {
        "client_id": "YOUR_APP_CLIENT_ID",
        "client_secret": "YOUR_APP_CLIENT_SECRET",
        "tenant_id": "common",
        "_setup_instructions": (
            "1. Go to https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade\n"
            "2. Click 'New registration'\n"
            "3. Name: 'Nellie Agent'\n"
            "4. Supported account types: 'Accounts in any organizational directory and personal Microsoft accounts'\n"
            "5. Redirect URI: http://localhost:8400/callback (Web)\n"
            "6. Copy Application (client) ID → client_id\n"
            "7. Go to 'Certificates & secrets' → 'New client secret' → copy value → client_secret\n"
            "8. Go to 'API permissions' → Add: Mail.Read, Mail.ReadWrite, Mail.Send, Calendars.Read, Files.Read, User.Read\n"
            "9. Grant admin consent"
        ),
    }
    CRED_FILE.write_text(json.dumps(template, indent=2), encoding="utf-8")
    print(f"Template created: {CRED_FILE}")
    print("Edit the file with your Azure AD app credentials.")
