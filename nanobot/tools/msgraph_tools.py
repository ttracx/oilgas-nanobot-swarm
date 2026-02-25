"""
Microsoft Graph Tools — allows nanobot agents to query Outlook email and calendar.

These tools are registered in the ToolRegistry so any agent in the swarm
can read emails, search mail, and check calendar during execution.
"""

import json
import time
import structlog

from nanobot.tools.base import BaseTool, ToolResult
from nanobot.integrations.microsoft_graph import ms_graph

log = structlog.get_logger()


class EmailSearchTool(BaseTool):
    """Search Outlook emails by subject, body, or sender."""

    name = "email_search"
    description = (
        "Search Nellie's Outlook email for messages matching a query. "
        "Returns subject, sender, date, and preview for each match. "
        "Use this to find emails about a topic, from a person, or containing keywords."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — matches subject, body, and sender",
            },
            "count": {
                "type": "integer",
                "description": "Maximum results to return (default: 10)",
                "default": 10,
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str, count: int = 10) -> ToolResult:
        t0 = time.time()
        try:
            if not ms_graph.creds.is_configured:
                await ms_graph.initialize()
            if not ms_graph.creds.is_token_valid:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output="Microsoft Graph not authenticated. Configure credentials at ~/.nellie/config/microsoft_graph.json",
                    duration_seconds=time.time() - t0,
                )
            results = await ms_graph.search_emails(query, count=count)
            output = json.dumps(results, indent=2, default=str)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output if results else f"No emails found matching '{query}'.",
                raw=results, duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Email search failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class EmailReadTool(BaseTool):
    """Read the full body of an email by message ID."""

    name = "email_read"
    description = (
        "Read the full body of an Outlook email. Requires the message ID "
        "(from email_search or email_recent results). Returns subject, sender, "
        "body content, and conversation context."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "message_id": {
                "type": "string",
                "description": "The email message ID to read",
            },
        },
        "required": ["message_id"],
    }

    async def run(self, message_id: str) -> ToolResult:
        t0 = time.time()
        try:
            if not ms_graph.creds.is_token_valid:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output="Microsoft Graph not authenticated.",
                    duration_seconds=time.time() - t0,
                )
            result = await ms_graph.get_email_body(message_id)
            if not result:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output=f"Email not found: {message_id[:20]}...",
                    duration_seconds=time.time() - t0,
                )
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output, raw=result, duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Email read failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class EmailRecentTool(BaseTool):
    """Get recent emails from the inbox."""

    name = "email_recent"
    description = (
        "Get the most recent emails from Nellie's Outlook inbox. "
        "Returns subject, sender, date, read status, and preview for each email. "
        "Use this for a quick scan of what's new."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of recent emails to fetch (default: 10)",
                "default": 10,
            },
            "folder": {
                "type": "string",
                "description": "Mail folder to read from (default: inbox)",
                "default": "inbox",
            },
        },
    }

    async def run(self, count: int = 10, folder: str = "inbox") -> ToolResult:
        t0 = time.time()
        try:
            if not ms_graph.creds.is_configured:
                await ms_graph.initialize()
            if not ms_graph.creds.is_token_valid:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output="Microsoft Graph not authenticated.",
                    duration_seconds=time.time() - t0,
                )
            results = await ms_graph.get_recent_emails(count=count, folder=folder)
            output = json.dumps(results, indent=2, default=str)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output if results else "No recent emails found.",
                raw=results, duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Email fetch failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class CalendarTodayTool(BaseTool):
    """Get today's calendar events."""

    name = "calendar_today"
    description = (
        "Get today's calendar events from Nellie's Outlook calendar. "
        "Returns event subject, start/end times, location, organizer, and attendees. "
        "Use this for daily briefings and agenda checks."
    )
    parameters_schema = {"type": "object", "properties": {}}

    async def run(self) -> ToolResult:
        t0 = time.time()
        try:
            if not ms_graph.creds.is_configured:
                await ms_graph.initialize()
            if not ms_graph.creds.is_token_valid:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output="Microsoft Graph not authenticated.",
                    duration_seconds=time.time() - t0,
                )
            results = await ms_graph.get_today_events()
            output = json.dumps(results, indent=2, default=str)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output if results else "No events on today's calendar.",
                raw=results, duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Calendar query failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class CalendarUpcomingTool(BaseTool):
    """Get upcoming calendar events for the next N days."""

    name = "calendar_upcoming"
    description = (
        "Get upcoming calendar events from Nellie's Outlook calendar. "
        "Defaults to next 7 days. Use this for weekly planning, "
        "meeting prep, and scheduling context."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Number of days ahead to look (default: 7)",
                "default": 7,
            },
        },
    }

    async def run(self, days: int = 7) -> ToolResult:
        t0 = time.time()
        try:
            if not ms_graph.creds.is_configured:
                await ms_graph.initialize()
            if not ms_graph.creds.is_token_valid:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output="Microsoft Graph not authenticated.",
                    duration_seconds=time.time() - t0,
                )
            results = await ms_graph.get_upcoming_events(days=days)
            output = json.dumps(results, indent=2, default=str)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output if results else f"No events in the next {days} days.",
                raw=results, duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Calendar query failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class EmailSendTool(BaseTool):
    """Send an email via Outlook."""

    name = "email_send"
    description = (
        "Send an email through Nellie's Outlook account. "
        "Requires recipient addresses, subject, and body. "
        "Body can be plain text or HTML. Use with care — this sends real emails."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of recipient email addresses",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Email body content (HTML or plain text)",
            },
            "body_type": {
                "type": "string",
                "enum": ["HTML", "Text"],
                "description": "Body content type (default: HTML)",
                "default": "HTML",
            },
        },
        "required": ["to", "subject", "body"],
    }

    async def run(
        self,
        to: list[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
    ) -> ToolResult:
        t0 = time.time()
        try:
            if not ms_graph.creds.is_token_valid:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output="Microsoft Graph not authenticated.",
                    duration_seconds=time.time() - t0,
                )
            sent = await ms_graph.send_email(to, subject, body, body_type=body_type)
            if sent:
                return ToolResult(
                    tool_name=self.name, success=True,
                    output=f"Email sent to {', '.join(to)} with subject '{subject}'.",
                    duration_seconds=time.time() - t0,
                )
            return ToolResult(
                tool_name=self.name, success=False,
                output="Failed to send email — check Graph API credentials and permissions.",
                duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Email send failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class EmailDraftTool(BaseTool):
    """Create an email draft in Outlook (not sent)."""

    name = "email_draft"
    description = (
        "Create a draft email in Nellie's Outlook Drafts folder. "
        "The email is NOT sent — it's saved for review. "
        "Use this for background email drafting workflows."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of recipient email addresses",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Email body content (HTML or plain text)",
            },
            "body_type": {
                "type": "string",
                "enum": ["HTML", "Text"],
                "description": "Body content type (default: HTML)",
                "default": "HTML",
            },
        },
        "required": ["to", "subject", "body"],
    }

    async def run(
        self,
        to: list[str],
        subject: str,
        body: str,
        body_type: str = "HTML",
    ) -> ToolResult:
        t0 = time.time()
        try:
            if not ms_graph.creds.is_token_valid:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output="Microsoft Graph not authenticated.",
                    duration_seconds=time.time() - t0,
                )
            result = await ms_graph.create_draft(to, subject, body, body_type=body_type)
            if result:
                draft_id = result.get("id", "unknown")
                return ToolResult(
                    tool_name=self.name, success=True,
                    output=f"Draft created for {', '.join(to)} — subject: '{subject}' (id: {draft_id[:20]}...)",
                    raw=result, duration_seconds=time.time() - t0,
                )
            return ToolResult(
                tool_name=self.name, success=False,
                output="Failed to create draft.",
                duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Draft creation failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


def register_msgraph_tools(registry) -> None:
    """Register all Microsoft Graph tools with a ToolRegistry."""
    registry.register(EmailSearchTool())
    registry.register(EmailReadTool())
    registry.register(EmailRecentTool())
    registry.register(CalendarTodayTool())
    registry.register(CalendarUpcomingTool())
    registry.register(EmailSendTool())
    registry.register(EmailDraftTool())
    log.info("msgraph_tools_registered", count=7)
