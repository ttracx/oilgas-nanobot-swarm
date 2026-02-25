"""
Knowledge Graph + Scheduler API routes.

Exposes the knowledge vault, graph builder, background scheduler,
and agent teams as REST endpoints under /v1/knowledge/ and /v1/scheduler/.
"""

import json
import structlog
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field

from nanobot.knowledge.vault import vault
from nanobot.knowledge.graph_builder import graph_builder
from nanobot.scheduler.scheduler import scheduler
from nanobot.scheduler.agent_teams import list_teams, get_team, TEAM_REGISTRY
from nanobot.integrations.microsoft_graph import ms_graph

log = structlog.get_logger()

# Reuse OpenClaw auth
from nanobot.integrations.openclaw_connector import verify_openclaw_key

router = APIRouter(prefix="/v1", tags=["Knowledge & Scheduler"])


# ── Knowledge Graph Endpoints ────────────────────────────────────────────


class NoteCreateRequest(BaseModel):
    category: str = Field(..., description="people, companies, projects, topics, decisions, commitments, meetings, or daily")
    name: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    backlinks: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    aliases: list[str] = Field(default_factory=list)


class NoteUpdateRequest(BaseModel):
    append_content: str | None = None
    new_backlinks: list[str] = Field(default_factory=list)
    update_metadata: dict = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str
    category: str | None = None
    max_results: int = 20


@router.get("/knowledge/stats")
async def knowledge_stats(_: str = Depends(verify_openclaw_key)):
    """Get knowledge vault statistics."""
    return vault.get_stats()


@router.get("/knowledge/index")
async def knowledge_index(_: str = Depends(verify_openclaw_key)):
    """Get the full knowledge graph index."""
    return vault.build_index()


@router.post("/knowledge/search")
async def knowledge_search(request: SearchRequest, _: str = Depends(verify_openclaw_key)):
    """Search the knowledge graph."""
    results = vault.search(request.query, category=request.category, max_results=request.max_results)
    return {"query": request.query, "results": results, "count": len(results)}


@router.get("/knowledge/notes")
async def list_notes(category: str | None = None, _: str = Depends(verify_openclaw_key)):
    """List all notes, optionally filtered by category."""
    notes = vault.list_notes(category=category)
    return {"notes": notes, "count": len(notes)}


@router.get("/knowledge/notes/{category}/{name}")
async def read_note(category: str, name: str, _: str = Depends(verify_openclaw_key)):
    """Read a specific note."""
    note = vault.read_note(category, name)
    if not note:
        raise HTTPException(404, f"Note not found: {category}/{name}")
    return note


@router.post("/knowledge/notes")
async def create_note(request: NoteCreateRequest, _: str = Depends(verify_openclaw_key)):
    """Create a new knowledge note."""
    path = vault.create_note(
        request.category, request.name, request.content,
        metadata=request.metadata, backlinks=request.backlinks or None,
        confidence=request.confidence,
        aliases=request.aliases or None,
    )
    return {"created": True, "path": str(path), "category": request.category, "name": request.name}


@router.put("/knowledge/notes/{category}/{name}")
async def update_note(
    category: str, name: str, request: NoteUpdateRequest,
    _: str = Depends(verify_openclaw_key),
):
    """Update an existing note."""
    path = vault.update_note(
        category, name,
        append_content=request.append_content,
        new_backlinks=request.new_backlinks if request.new_backlinks else None,
        update_metadata=request.update_metadata if request.update_metadata else None,
    )
    if not path:
        raise HTTPException(404, f"Note not found: {category}/{name}")
    return {"updated": True, "path": str(path)}


@router.delete("/knowledge/notes/{category}/{name}")
async def delete_note(category: str, name: str, _: str = Depends(verify_openclaw_key)):
    """Delete a note."""
    deleted = vault.delete_note(category, name)
    if not deleted:
        raise HTTPException(404, f"Note not found: {category}/{name}")
    return {"deleted": True}


@router.get("/knowledge/backlinks/{entity}")
async def get_backlinks(entity: str, _: str = Depends(verify_openclaw_key)):
    """Find all notes that link to a specific entity."""
    results = vault.find_backlinks_to(entity)
    return {"entity": entity, "referencing_notes": results, "count": len(results)}


@router.get("/knowledge/graph-builder/status")
async def graph_builder_status(_: str = Depends(verify_openclaw_key)):
    """Get the graph builder status."""
    return graph_builder.get_status()


@router.post("/knowledge/graph-builder/rebuild")
async def rebuild_graph(_: str = Depends(verify_openclaw_key)):
    """Force a full knowledge graph rebuild."""
    index = await graph_builder.force_rebuild()
    return {"rebuilt": True, "index": index}


# ── Scheduler Endpoints ──────────────────────────────────────────────────


class ScheduleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    team: str
    schedule_type: str = "cron"
    expression: str = "08:00"
    starting_message: str = ""
    enabled: bool = True
    context: dict = Field(default_factory=dict)


class TeamRunRequest(BaseModel):
    team: str
    task: str
    context: dict = Field(default_factory=dict)


@router.get("/scheduler/status")
async def scheduler_status(_: str = Depends(verify_openclaw_key)):
    """Get the full scheduler status including all schedules and their state."""
    return scheduler.get_status()


@router.get("/scheduler/teams")
async def available_teams(_: str = Depends(verify_openclaw_key)):
    """List all available agent teams."""
    return {"teams": list_teams()}


@router.get("/scheduler/teams/{team_name}")
async def team_detail(team_name: str, _: str = Depends(verify_openclaw_key)):
    """Get details about a specific agent team."""
    team = get_team(team_name)
    if not team:
        raise HTTPException(404, f"Team not found: {team_name}")
    return {
        "name": team.name,
        "description": team.description,
        "mode": team.mode,
        "system_prompt": team.system_prompt,
        "inject_knowledge": team.inject_knowledge,
        "inject_history": team.inject_history,
        "update_knowledge_after": team.update_knowledge_after,
    }


@router.post("/scheduler/schedules")
async def create_schedule(request: ScheduleCreateRequest, _: str = Depends(verify_openclaw_key)):
    """Create a new schedule entry."""
    if not get_team(request.team):
        raise HTTPException(400, f"Unknown team: {request.team}. Available: {list(TEAM_REGISTRY.keys())}")
    scheduler.add_schedule(request.model_dump())
    return {"created": True, "name": request.name, "team": request.team}


@router.delete("/scheduler/schedules/{name}")
async def delete_schedule(name: str, _: str = Depends(verify_openclaw_key)):
    """Remove a schedule."""
    scheduler.remove_schedule(name)
    return {"deleted": True, "name": name}


@router.post("/scheduler/schedules/{name}/toggle")
async def toggle_schedule(name: str, enabled: bool = True, _: str = Depends(verify_openclaw_key)):
    """Enable or disable a schedule."""
    result = scheduler.toggle_schedule(name, enabled)
    if not result:
        raise HTTPException(404, f"Schedule not found: {name}")
    return {"name": name, "enabled": enabled}


@router.post("/scheduler/schedules/{name}/trigger")
async def trigger_schedule(name: str, _: str = Depends(verify_openclaw_key)):
    """Manually trigger a scheduled run immediately."""
    result = await scheduler.trigger_now(name)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/scheduler/run-team")
async def run_team(request: TeamRunRequest, _: str = Depends(verify_openclaw_key)):
    """Run an agent team immediately with a custom task."""
    result = await scheduler.run_team_now(request.team, request.task, request.context)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ── Microsoft Graph Endpoints ────────────────────────────────────────────


@router.get("/msgraph/status")
async def msgraph_status(_: str = Depends(verify_openclaw_key)):
    """Get Microsoft Graph integration status."""
    return await ms_graph.get_status()


@router.post("/msgraph/initialize")
async def msgraph_initialize(_: str = Depends(verify_openclaw_key)):
    """Initialize or re-initialize the Microsoft Graph client."""
    success = await ms_graph.initialize()
    status = await ms_graph.get_status()
    return {"initialized": success, **status}


@router.get("/msgraph/me")
async def msgraph_me(_: str = Depends(verify_openclaw_key)):
    """Get the authenticated user's profile."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    profile = await ms_graph.get_me()
    if not profile:
        raise HTTPException(401, "Not authenticated with Microsoft Graph")
    return profile


@router.get("/msgraph/emails/recent")
async def msgraph_recent_emails(
    count: int = 20,
    folder: str = "inbox",
    _: str = Depends(verify_openclaw_key),
):
    """Get recent emails from Outlook."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    emails = await ms_graph.get_recent_emails(count=count, folder=folder)
    return {"emails": emails, "count": len(emails)}


@router.get("/msgraph/emails/{message_id}")
async def msgraph_read_email(message_id: str, _: str = Depends(verify_openclaw_key)):
    """Read the full body of an email."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    email = await ms_graph.get_email_body(message_id)
    if not email:
        raise HTTPException(404, "Email not found")
    return email


class EmailSearchRequest(BaseModel):
    query: str
    count: int = 10


@router.post("/msgraph/emails/search")
async def msgraph_search_emails(request: EmailSearchRequest, _: str = Depends(verify_openclaw_key)):
    """Search emails by subject, body, or sender."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    results = await ms_graph.search_emails(request.query, count=request.count)
    return {"query": request.query, "results": results, "count": len(results)}


class EmailSendRequest(BaseModel):
    to: list[str]
    subject: str
    body: str
    body_type: str = "HTML"
    save_to_sent: bool = True


@router.post("/msgraph/emails/send")
async def msgraph_send_email(request: EmailSendRequest, _: str = Depends(verify_openclaw_key)):
    """Send an email via Outlook."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    sent = await ms_graph.send_email(
        request.to, request.subject, request.body,
        body_type=request.body_type, save_to_sent=request.save_to_sent,
    )
    if not sent:
        raise HTTPException(500, "Failed to send email")
    return {"sent": True, "to": request.to, "subject": request.subject}


class EmailDraftRequest(BaseModel):
    to: list[str]
    subject: str
    body: str
    body_type: str = "HTML"


@router.post("/msgraph/emails/draft")
async def msgraph_create_draft(request: EmailDraftRequest, _: str = Depends(verify_openclaw_key)):
    """Create an email draft (not sent)."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    draft = await ms_graph.create_draft(
        request.to, request.subject, request.body, body_type=request.body_type,
    )
    if not draft:
        raise HTTPException(500, "Failed to create draft")
    return {"created": True, "draft_id": draft.get("id", ""), "subject": request.subject}


@router.get("/msgraph/calendar/today")
async def msgraph_today_events(_: str = Depends(verify_openclaw_key)):
    """Get today's calendar events."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    events = await ms_graph.get_today_events()
    return {"events": events, "count": len(events)}


@router.get("/msgraph/calendar/upcoming")
async def msgraph_upcoming_events(days: int = 7, _: str = Depends(verify_openclaw_key)):
    """Get upcoming calendar events for the next N days."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    events = await ms_graph.get_upcoming_events(days=days)
    return {"events": events, "count": len(events)}


@router.post("/msgraph/emails/ingest")
async def msgraph_ingest_emails(count: int = 10, _: str = Depends(verify_openclaw_key)):
    """Fetch recent emails and ingest them into the knowledge graph."""
    if not ms_graph.creds.is_token_valid:
        await ms_graph.initialize()
    if not ms_graph.creds.is_token_valid:
        raise HTTPException(401, "Microsoft Graph not authenticated")

    emails = await ms_graph.get_recent_emails(count=count)
    ingested = 0

    for email in emails:
        msg_id = email.get("id", "")
        full = await ms_graph.get_email_body(msg_id)
        if not full:
            continue

        text = (
            f"Email from {email.get('from', 'unknown')} ({email.get('from_email', '')})\n"
            f"Subject: {email.get('subject', '')}\n"
            f"Date: {email.get('received', '')}\n\n"
            f"{full.get('body', '')[:3000]}"
        )

        created = await graph_builder._extract_and_store(text, "email", f"msgraph:{msg_id[:20]}")
        ingested += created

    return {"emails_processed": len(emails), "entities_created": ingested}
