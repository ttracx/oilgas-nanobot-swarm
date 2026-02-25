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
from nanobot.core.claude_runner import ClaudeTeamRunner
from nanobot.state.swarm_state import SwarmStateManager
from nanobot.integrations.nellie_memory_bridge import memory_bridge
from nanobot.knowledge.graph_builder import graph_builder
from nanobot.knowledge.artifact_writer import process_agent_output

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
_claude_runner: ClaudeTeamRunner | None = None
_vector_store = None
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
    claude_runner: ClaudeTeamRunner | None = None,
    vector_store=None,
) -> None:
    """Called during gateway startup to inject swarm instances."""
    global _hierarchical_swarm, _flat_swarm, _claude_runner, _vector_store
    _hierarchical_swarm = hierarchical
    _flat_swarm = flat
    _claude_runner = claude_runner
    _vector_store = vector_store
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
    models = [
        ModelInfo(id="nanobot-swarm-hierarchical").model_dump(),
        ModelInfo(id="nanobot-swarm-flat").model_dump(),
        ModelInfo(id="nanobot-reasoner").model_dump(),
        ModelInfo(id="nanobot-nellie-memory").model_dump(),
    ]
    if _claude_runner:
        models.append(ModelInfo(id="nanobot-claude").model_dump())
    return {"object": "list", "data": models}


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


def _build_vault_context(goal: str, max_tokens: int = 1500) -> str:
    """Build vault knowledge context for a request.

    Combines:
    1. Graph builder's daily context (today's note + recent entities)
    2. Vector semantic search results relevant to the goal
    """
    parts: list[str] = []

    # 1. Graph context (daily note + recently updated notes)
    try:
        graph_ctx = graph_builder.load_graph_context(token_budget=max_tokens // 2)
        if graph_ctx and graph_ctx != "(empty vault)":
            parts.append(graph_ctx)
    except Exception as e:
        log.warning("vault_context_graph_failed", error=str(e))

    # 2. Vector semantic search on the goal
    if _vector_store and goal:
        try:
            results = _vector_store.hybrid_search(goal, top_k=5)
            if results:
                snippets = []
                for r in results:
                    if r.score > 0.15:  # Only include relevant results
                        snippets.append(f"- **{r.title}** ({r.entity_type}): {r.snippet[:200]}")
                if snippets:
                    parts.append("## Relevant Knowledge\n" + "\n".join(snippets))
        except Exception as e:
            log.warning("vault_context_vector_failed", error=str(e))

    return "\n\n---\n\n".join(parts) if parts else ""


@router.post("/chat/completions")
async def chat_completions(request: ChatCompletionRequest, _: str = Depends(verify_openclaw_key)):
    """
    OpenAI-compatible chat completions endpoint.
    Nellie sends a message -> swarm decomposes and executes -> returns result.

    The last user message becomes the swarm's goal.
    System messages provide context/instructions.

    Models:
    - nanobot-swarm-hierarchical: 3-tier swarm decomposition
    - nanobot-swarm-flat: simple parallel swarm
    - nanobot-nellie-memory: memory-aware — injects vault context, extracts + saves knowledge
    - nanobot-claude: routes to Claude agent with full tool access
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

    # Load vault knowledge context (entities, relationships, daily notes)
    vault_context = ""
    is_memory_model = request.model in ("nanobot-nellie-memory", "nanobot-claude")
    try:
        vault_context = _build_vault_context(goal, max_tokens=2000 if is_memory_model else 1000)
    except Exception as e:
        log.warning("vault_context_build_failed", error=str(e))

    # Prepend system context + Nellie memory + vault knowledge to goal
    context_parts = []
    if system_context.strip():
        context_parts.append(f"Context from Nellie:\n{system_context.strip()}")
    if nellie_context:
        context_parts.append(nellie_context)
    if vault_context:
        context_parts.append(f"## Knowledge Vault\n{vault_context}")

    if context_parts:
        full_goal = "\n\n".join(context_parts) + f"\n\nTask:\n{goal}"
    else:
        full_goal = goal

    # For memory model, add instruction to save new knowledge
    if is_memory_model:
        full_goal += (
            "\n\n---\n"
            "IMPORTANT: After completing the task, identify any new facts, "
            "people, decisions, or relationships learned. Emit them as graph updates "
            "using <graph_update path=\"category/entity-name.md\">content</graph_update> tags "
            "so they are saved to long-term memory for future sessions."
        )

    # Route to the appropriate backend
    if request.model == "nanobot-claude":
        if not _claude_runner:
            raise HTTPException(503, "Claude runner not available — set ANTHROPIC_API_KEY")
        result = await _claude_runner.run(full_goal, mode="flat", context=request.metadata)
    elif request.model in ("nanobot-swarm-hierarchical", "nanobot-swarm"):
        if _hierarchical_swarm is None:
            raise HTTPException(503, "Hierarchical swarm not ready")
        result = await _hierarchical_swarm.run(full_goal, request.metadata)
    elif request.model in ("nanobot-swarm-flat", "nanobot-nellie-memory"):
        if request.model == "nanobot-nellie-memory" and _claude_runner:
            # Memory model prefers Claude when available (better at tool use)
            result = await _claude_runner.run(full_goal, mode="flat", context=request.metadata)
        elif _flat_swarm is not None:
            result = await _flat_swarm.run(full_goal, request.metadata)
        else:
            raise HTTPException(503, "Flat swarm not ready")
    else:
        raise HTTPException(400, f"Unknown model: {request.model}")

    # Auto-persist result to Nellie's memory bridge (HISTORY.md + Redis)
    try:
        session_id_val = result.get("session_id", "unknown")
        await memory_bridge.persist_swarm_result(session_id_val, result)
    except Exception as e:
        log.warning("result_persist_failed", error=str(e))

    # Extract artifacts and graph updates from the response → write to vault
    final_answer = result.get("final_answer", "")
    extraction_summary = ""
    try:
        extraction = process_agent_output(
            final_answer,
            agent_id=f"openclaw-{request.model}",
        )
        if extraction.artifacts_written > 0 or extraction.graph_updates_applied > 0:
            extraction_summary = (
                f" [Memory: +{extraction.artifacts_written} artifacts, "
                f"+{extraction.graph_updates_applied} knowledge updates]"
            )
            log.info(
                "openclaw_memory_updated",
                model=request.model,
                artifacts=extraction.artifacts_written,
                graph_updates=extraction.graph_updates_applied,
            )
    except Exception as e:
        log.warning("artifact_extraction_failed", error=str(e))

    # Notify graph builder of swarm completion for entity extraction
    try:
        await graph_builder.events.emit("swarm_complete", {
            "session_id": result.get("session_id", ""),
            "goal": goal,
            "final_answer": final_answer,
        })
    except Exception as e:
        log.warning("graph_builder_notify_failed", error=str(e))

    if not result.get("success"):
        error_msg = result.get("error", "Swarm execution failed")
        response_content = f"[SWARM ERROR] {error_msg}"
    else:
        response_content = final_answer

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
        f"{extraction_summary}"
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
    """Query Nellie's persistent memory — vault knowledge + swarm history + Redis state."""
    try:
        recent_results = await memory_bridge.get_recent_swarm_history(20)
        nellie_context = await memory_bridge.load_nellie_context()
        bridge_status = await memory_bridge.get_bridge_status()
        vault_ctx = graph_builder.load_graph_context(token_budget=1500)
        vault_stats = await memory_bridge.get_vault_stats()

        return {
            "long_term_memory": nellie_context[:2000] if nellie_context else None,
            "vault_context": vault_ctx if vault_ctx != "(empty vault)" else None,
            "vault_stats": vault_stats,
            "recent_swarm_results": recent_results,
            "bridge_status": bridge_status,
        }
    except Exception as e:
        raise HTTPException(500, f"Memory query failed: {e}")


class MemorySearchRequest(BaseModel):
    query: str
    category: str | None = None
    max_results: int = 10


@router.post("/nellie/memory/search")
async def nellie_memory_search(request: MemorySearchRequest, _: str = Depends(verify_openclaw_key)):
    """Semantic search across Nellie's knowledge vault — combines vector + graph search."""
    results = []

    # Vector semantic search
    if _vector_store:
        try:
            vector_results = _vector_store.hybrid_search(
                request.query, top_k=request.max_results,
                type_filter=request.category,
            )
            for r in vector_results:
                results.append({
                    "source": "semantic",
                    "score": r.score,
                    "title": r.title,
                    "type": r.entity_type,
                    "path": r.path,
                    "tags": r.tags,
                    "snippet": r.snippet,
                })
        except Exception as e:
            log.warning("memory_search_vector_failed", error=str(e))

    # Graph keyword search
    try:
        from nanobot.knowledge.vault import vault
        graph_results = vault.search(request.query, category=request.category, max_results=request.max_results)
        seen = {r["path"] for r in results}
        for gr in graph_results:
            path = gr.get("path", "")
            if path not in seen:
                results.append({
                    "source": "graph",
                    "score": 0.5,
                    "title": gr.get("name", ""),
                    "type": gr.get("category", ""),
                    "path": path,
                    "tags": gr.get("tags", []),
                    "snippet": gr.get("content", "")[:300],
                })
    except Exception as e:
        log.warning("memory_search_graph_failed", error=str(e))

    # Also search Redis bridge for recent swarm results
    try:
        redis_results = await memory_bridge.search_swarm_history(request.query)
        for rr in redis_results:
            results.append({
                "source": "swarm_history",
                "score": rr.get("relevance", 0.3),
                "title": f"Swarm: {rr.get('goal', '')[:60]}",
                "type": "swarm_session",
                "path": f"swarm:{rr.get('session_id', '')[:12]}",
                "tags": [],
                "snippet": rr.get("final_answer", "")[:300],
            })
    except Exception as e:
        log.warning("memory_search_redis_failed", error=str(e))

    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "query": request.query,
        "results": results[:request.max_results],
        "count": len(results),
    }


class MemorySaveRequest(BaseModel):
    category: str
    name: str
    content: str
    backlinks: list[str] = Field(default_factory=list)
    confidence: float = 0.85


@router.post("/nellie/memory/save")
async def nellie_memory_save(request: MemorySaveRequest, _: str = Depends(verify_openclaw_key)):
    """Save knowledge directly to Nellie's vault and sync to Redis."""
    from nanobot.knowledge.vault import vault

    existing = vault.read_note(request.category, request.name)
    if existing:
        vault.update_note(
            request.category, request.name,
            append_content=request.content,
            new_backlinks=request.backlinks or None,
            new_confidence=request.confidence,
        )
        action = "updated"
    else:
        vault.create_note(
            request.category, request.name, request.content,
            backlinks=request.backlinks or None,
            confidence=request.confidence,
        )
        action = "created"

    # Sync to Redis for cross-session access
    try:
        await memory_bridge.sync_vault_entry(request.category, request.name, request.content)
    except Exception as e:
        log.warning("memory_save_redis_sync_failed", error=str(e))

    # Update vector index
    if _vector_store:
        try:
            from nanobot.knowledge.vault import _slugify
            note_path = vault.root / request.category / f"{_slugify(request.name)}.md"
            if note_path.exists():
                _vector_store.index_note(str(note_path))
        except Exception as e:
            log.warning("memory_save_vector_failed", error=str(e))

    return {
        "action": action,
        "category": request.category,
        "name": request.name,
        "backlinks": request.backlinks,
    }


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
