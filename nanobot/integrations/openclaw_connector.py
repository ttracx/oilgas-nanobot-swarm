"""
OpenClaw/Nellie Integration Connector
Exposes the nanobot swarm as an OpenAI-compatible endpoint that
Nellie (OpenClaw agent) can use for sub-agent delegation.

Nellie sends tasks to the swarm via:
1. OpenAI-compatible chat/completions endpoint (pretends to be a model)
2. Direct swarm API for advanced orchestration
3. WebSocket for real-time status updates

Features:
- Persistent memory bridge: swarm results auto-persist to NellieNano's HISTORY.md
- Workspace sync: swarm output artifacts synced to Nellie's workspace
- Session continuity: cross-session recall via Redis-backed bridge store

This allows Nellie to manage nanobot teams under her supervision.
"""

import asyncio
import json
import os
import time
import uuid
import structlog
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Header, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nanobot.core.hierarchical_swarm import HierarchicalSwarm
from nanobot.core.orchestrator import NanobotSwarm
from nanobot.state.swarm_state import SwarmStateManager
from nanobot.integrations.nellie_memory_bridge import memory_bridge

log = structlog.get_logger()

OPENCLAW_API_KEY = os.getenv(
    "OPENCLAW_API_KEY", "nq-openclaw-0oQB26o-WlboQ3CovKhAm-aPbCnui_jeY11XmZy-i1g"
)


def verify_openclaw_key(authorization: str = Header(None)):
    """Verify Bearer token for OpenClaw routes."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization format. Use: Bearer <key>")
    if parts[1] != OPENCLAW_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return parts[1]


router = APIRouter(prefix="/v1", tags=["OpenAI-Compatible"])

# Will be set during app startup
_hierarchical_swarm: HierarchicalSwarm | None = None
_flat_swarm: NanobotSwarm | None = None
_state_manager = SwarmStateManager()


async def _init_bridge() -> None:
    """Initialize the Nellie memory bridge."""
    try:
        await memory_bridge.initialize()
        log.info("nellie_memory_bridge_initialized")
    except Exception as e:
        log.warning("nellie_memory_bridge_init_failed", error=str(e))


def set_swarm_instances(
    hierarchical: HierarchicalSwarm,
    flat: NanobotSwarm,
) -> None:
    """Called during gateway startup to inject swarm instances."""
    global _hierarchical_swarm, _flat_swarm
    _hierarchical_swarm = hierarchical
    _flat_swarm = flat
    # Schedule bridge initialization
    asyncio.get_event_loop().create_task(_init_bridge())


# ── OpenAI-compatible models endpoint ────────────────────────────────────


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 1700000000
    owned_by: str = "neuralquantum"


@router.get("/models")
async def list_models(_: str = Depends(verify_openclaw_key)):
    """Return available models — allows Nellie to discover the swarm."""
    return {
        "object": "list",
        "data": [
            ModelInfo(id="nanobot-swarm-hierarchical").model_dump(),
            ModelInfo(id="nanobot-swarm-flat").model_dump(),
            ModelInfo(id="nanobot-reasoner").model_dump(),
        ],
    }


# ── OpenAI-compatible chat completions ───────────────────────────────────


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "nanobot-swarm-hierarchical"
    messages: list[ChatMessage]
    temperature: float = 0.1
    max_tokens: int = 4096
    stream: bool = False
    metadata: dict = Field(default_factory=dict)


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Usage


@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest, _: str = Depends(verify_openclaw_key)):
    """
    OpenAI-compatible chat completions endpoint.
    Nellie sends a message -> swarm decomposes and executes -> returns result.

    The last user message becomes the swarm's goal.
    System messages provide context/instructions.
    """
    # Extract the goal from messages
    system_context = ""
    goal = ""

    for msg in request.messages:
        if msg.role == "system":
            system_context += msg.content + "\n"
        elif msg.role == "user":
            goal = msg.content

    if not goal:
        raise HTTPException(400, "No user message found in request")

    # Preflight: load Nellie's long-term memory for context
    nellie_context = ""
    try:
        nellie_context = await memory_bridge.load_nellie_context()
    except Exception as e:
        log.warning("preflight_memory_load_failed", error=str(e))

    # Prepend system context + Nellie memory to goal
    context_parts = []
    if system_context.strip():
        context_parts.append(f"Context from Nellie:\n{system_context.strip()}")
    if nellie_context:
        context_parts.append(nellie_context)

    if context_parts:
        full_goal = "\n\n".join(context_parts) + f"\n\nTask:\n{goal}"
    else:
        full_goal = goal

    # Determine which swarm to use
    if request.model in ("nanobot-swarm-hierarchical", "nanobot-swarm"):
        if _hierarchical_swarm is None:
            raise HTTPException(503, "Hierarchical swarm not ready")
        result = await _hierarchical_swarm.run(full_goal, request.metadata)
    elif request.model == "nanobot-swarm-flat":
        if _flat_swarm is None:
            raise HTTPException(503, "Flat swarm not ready")
        result = await _flat_swarm.run(full_goal, request.metadata)
    else:
        raise HTTPException(400, f"Unknown model: {request.model}")

    # Auto-persist result to Nellie's memory
    try:
        session_id_val = result.get("session_id", "unknown")
        await memory_bridge.persist_swarm_result(session_id_val, result)
    except Exception as e:
        log.warning("result_persist_failed", error=str(e))

    if not result.get("success"):
        error_msg = result.get("error", "Swarm execution failed")
        # Return error as assistant message rather than HTTP error
        # so Nellie can handle it gracefully
        response_content = f"[SWARM ERROR] {error_msg}"
    else:
        response_content = result["final_answer"]

    # Build response metadata for Nellie
    session_id = result.get("session_id", "unknown")
    summary = result.get("session_summary", {})

    # Append execution metadata as a footer
    meta_footer = (
        f"\n\n---\n"
        f"[Swarm Session: {session_id}] "
        f"[Tasks: {summary.get('total_tasks', 0)}] "
        f"[Success Rate: {summary.get('success_rate', 0)}%] "
        f"[Tokens: {summary.get('total_tokens', 0)}]"
    )

    if request.stream:
        return StreamingResponse(
            _stream_response(
                response_content + meta_footer,
                request.model,
                session_id,
            ),
            media_type="text/event-stream",
        )

    return ChatCompletionResponse(
        id=f"chatcmpl-swarm-{session_id[:8]}",
        created=int(time.time()),
        model=request.model,
        choices=[
            ChatChoice(
                message=ChatMessage(
                    role="assistant",
                    content=response_content + meta_footer,
                ),
            )
        ],
        usage=Usage(
            prompt_tokens=len(full_goal.split()),
            completion_tokens=len(response_content.split()),
            total_tokens=summary.get("total_tokens", 0),
        ),
    )


async def _stream_response(
    content: str,
    model: str,
    session_id: str,
) -> AsyncIterator[str]:
    """Stream the response in SSE format (OpenAI-compatible)."""
    chunk_id = f"chatcmpl-swarm-{session_id[:8]}"

    # Stream in word-sized chunks for realistic streaming
    words = content.split()
    for i, word in enumerate(words):
        token = word + (" " if i < len(words) - 1 else "")
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": token},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.01)

    # Final chunk
    final = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


# ── Nellie-specific management endpoints ─────────────────────────────────


class NellieTaskRequest(BaseModel):
    """Nellie's direct task dispatch format."""
    task: str
    team: str = "auto"  # auto, coder, researcher, analyst, validator, executor
    priority: int = 5
    context: dict = Field(default_factory=dict)
    callback_url: str | None = None


class NellieTaskResponse(BaseModel):
    session_id: str
    status: str
    result: str | None = None
    team_used: str | None = None
    tasks_completed: int = 0
    tokens_used: int = 0


@router.post("/nellie/dispatch", response_model=NellieTaskResponse)
async def nellie_dispatch(request: NellieTaskRequest, _: str = Depends(verify_openclaw_key)):
    """
    Nellie's direct dispatch endpoint — she can specify which team to use.
    This bypasses the Queen and sends directly to an L1 team.
    """
    if _hierarchical_swarm is None:
        raise HTTPException(503, "Swarm not ready")

    # For 'auto' mode, use full hierarchical swarm
    if request.team == "auto":
        result = await _hierarchical_swarm.run(
            request.task,
            {"nellie_priority": request.priority, **request.context},
        )
        # Auto-persist
        try:
            await memory_bridge.persist_swarm_result(
                result.get("session_id", ""), result
            )
        except Exception as e:
            log.warning("dispatch_persist_failed", error=str(e))

        return NellieTaskResponse(
            session_id=result.get("session_id", ""),
            status="complete" if result.get("success") else "failed",
            result=result.get("final_answer"),
            team_used="hierarchical",
            tasks_completed=len(result.get("l1_results", [])),
            tokens_used=result.get("session_summary", {}).get("total_tokens", 0),
        )

    # For specific team, use flat swarm with role-focused prompt
    if _flat_swarm is None:
        raise HTTPException(503, "Flat swarm not ready")

    team_prefixed_goal = (
        f"[TEAM: {request.team.upper()}] "
        f"Priority: {request.priority}/10\n\n"
        f"{request.task}"
    )
    result = await _flat_swarm.run(team_prefixed_goal, request.context)

    # Auto-persist
    try:
        await memory_bridge.persist_swarm_result(
            result.get("session_id", ""), result
        )
    except Exception as e:
        log.warning("dispatch_persist_failed", error=str(e))

    return NellieTaskResponse(
        session_id=result.get("session_id", ""),
        status="complete" if result.get("success") else "failed",
        result=result.get("final_answer"),
        team_used=request.team,
        tasks_completed=len(result.get("subtask_results", [])),
        tokens_used=result.get("session_summary", {}).get("total_tokens", 0),
    )


@router.get("/nellie/sessions")
async def nellie_sessions(_: str = Depends(verify_openclaw_key)):
    """Nellie queries her swarm session history."""
    sessions = await _state_manager.list_recent_sessions(20)
    return {
        "managed_by": "nellie",
        "total_sessions": len(sessions),
        "sessions": [
            {
                "id": s["session_id"],
                "goal": s.get("goal", "")[:100],
                "status": s.get("status"),
                "success": s.get("success"),
                "created": s.get("created_at"),
            }
            for s in sessions
        ],
    }


@router.get("/nellie/health")
async def nellie_health(_: str = Depends(verify_openclaw_key)):
    """Nellie checks her nanobot swarm health."""
    health = await _state_manager.get_swarm_health()
    bridge_status = {}
    try:
        bridge_status = await memory_bridge.get_bridge_status()
    except Exception as e:
        bridge_status = {"status": "error", "error": str(e)}

    return {
        "swarm_status": "operational" if health["active_agents"] >= 0 else "degraded",
        "active_nanobots": health["active_agents"],
        "role_distribution": health["agent_breakdown"],
        "failed_queue": health["failed_queue_depth"],
        "redis_memory_mb": health["redis_memory_used_mb"],
        "memory_bridge": bridge_status,
    }


@router.get("/nellie/memory")
async def nellie_memory(_: str = Depends(verify_openclaw_key)):
    """Query Nellie's persistent memory and swarm history."""
    try:
        recent_results = await memory_bridge.get_recent_swarm_history(20)
        nellie_context = await memory_bridge.load_nellie_context()
        bridge_status = await memory_bridge.get_bridge_status()
        return {
            "long_term_memory": nellie_context[:2000] if nellie_context else None,
            "recent_swarm_results": recent_results,
            "bridge_status": bridge_status,
        }
    except Exception as e:
        raise HTTPException(500, f"Memory query failed: {e}")


@router.post("/nellie/memory/sync")
async def nellie_memory_sync(request: Request, _: str = Depends(verify_openclaw_key)):
    """Force sync workspace artifacts from a swarm session."""
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")

    # Get session results from state manager
    session = await _state_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # Persist to memory bridge
    await memory_bridge.persist_swarm_result(session_id, session)

    # If artifacts provided, sync to workspace
    artifacts = body.get("artifacts", {})
    if artifacts:
        await memory_bridge.sync_workspace(session_id, artifacts)

    return {
        "synced": True,
        "session_id": session_id,
        "artifacts_synced": len(artifacts),
    }
