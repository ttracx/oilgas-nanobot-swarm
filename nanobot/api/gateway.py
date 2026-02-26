"""
NeuralQuantum Nanobot Swarm Gateway
REST API for external systems (including OpenClaw/Nellie) to dispatch goals.
"""

import os
import structlog
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nanobot.core.hierarchical_swarm import HierarchicalSwarm
from nanobot.core.orchestrator import NanobotSwarm
from nanobot.core.claude_runner import ClaudeTeamRunner
from nanobot.core.roles import L1Role, L2Role
from nanobot.state.swarm_state import SwarmStateManager
from nanobot.state.task_journal import TaskJournal
from nanobot.state.connection import close_pool
from nanobot.integrations.openclaw_connector import router as openclaw_router, set_swarm_instances
from nanobot.api.knowledge_routes import router as knowledge_router, set_vector_store
from nanobot.knowledge.graph_builder import graph_builder
from nanobot.scheduler.scheduler import scheduler
from nanobot.scheduler.agent_teams import get_team
from nanobot.tools.knowledge_tools import register_knowledge_tools
from nanobot.tools.msgraph_tools import register_msgraph_tools
from nanobot.tools.vault_memory_tools import register_vault_memory_tools, set_vector_store as set_memory_vector_store
from nanobot.tools.base import ToolRegistry
from nanobot.tools.oilgas_tools import get_oilgas_tools
from nanobot.integrations.microsoft_graph import ms_graph
from nanobot.integrations.nellie_memory_bridge import memory_bridge
from nanobot.knowledge.vector_store import VaultVectorStore
from nanobot.knowledge.file_watcher import VaultFileWatcher
from nanobot.knowledge.vault import vault

log = structlog.get_logger()

GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "nq-gateway-key")
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "nq-nanobot")
WARMUP_MODEL = os.getenv("WARMUP_MODEL", "")  # e.g. "qwen3-coder-next" — empty to skip
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

hierarchical_swarm: HierarchicalSwarm | None = None
flat_swarm: NanobotSwarm | None = None
claude_runner: ClaudeTeamRunner | None = None
vector_store: VaultVectorStore | None = None
file_watcher: VaultFileWatcher | None = None
state_manager = SwarmStateManager()


async def _warmup_models() -> None:
    """Ping the LLM backend with a tiny generation to warm up model loading."""
    if not WARMUP_MODEL:
        return
    models = [m.strip() for m in WARMUP_MODEL.split(",") if m.strip()]
    base_url = VLLM_URL.rstrip("/").removesuffix("/v1")

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=30, pool=30)) as client:
        for model in models:
            try:
                resp = await client.post(
                    f"{base_url}/api/generate",
                    json={"model": model, "prompt": "ping", "stream": False, "options": {"num_predict": 8}},
                )
                log.info("warmup_complete", model=model, status=resp.status_code)
            except Exception as e:
                # Also try OpenAI-compatible endpoint
                try:
                    resp = await client.post(
                        f"{base_url}/v1/chat/completions",
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 8,
                            "stream": False,
                        },
                        headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
                    )
                    log.info("warmup_complete", model=model, status=resp.status_code, endpoint="openai")
                except Exception as e2:
                    log.warning("warmup_failed", model=model, error=str(e2)[:100])


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hierarchical_swarm, flat_swarm, claude_runner
    log.info("gateway_startup")
    hierarchical_swarm = HierarchicalSwarm(
        vllm_url=VLLM_URL,
        api_key=VLLM_API_KEY,
        max_concurrent_l1=3,
        max_concurrent_global=12,
    )
    flat_swarm = NanobotSwarm(
        vllm_url=VLLM_URL,
        api_key=VLLM_API_KEY,
        max_parallel_agents=8,
    )
    # Initialize Claude runner if API key is available
    if ANTHROPIC_API_KEY:
        claude_runner = ClaudeTeamRunner()
        log.info("claude_runner_initialized", model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"))
    else:
        log.info("claude_runner_skipped", reason="ANTHROPIC_API_KEY not set")

    # Warmup models in background — don't block startup
    import asyncio
    asyncio.create_task(_warmup_models())

    # Initialize Microsoft Graph (non-blocking — skips if not configured)
    try:
        ms_initialized = await ms_graph.initialize()
        log.info("ms_graph_initialized", success=ms_initialized)
    except Exception as e:
        log.warning("ms_graph_init_skipped", error=str(e)[:100])

    # Start knowledge graph builder (background async task)
    graph_builder.start()
    log.info("graph_builder_started")

    # Initialize vector store (local hash embeddings — no API key needed)
    try:
        vector_store = VaultVectorStore(vault.root)
        loaded = vector_store.load()
        if loaded == 0:
            # First run — build the full index
            stats = vector_store.index_all()
            log.info("vector_store_built", **stats)
        else:
            log.info("vector_store_loaded", entries=loaded)
        # Optionally upgrade to OpenAI embeddings
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key:
            vector_store.configure_openai(openai_key)
            log.info("vector_store_upgraded_to_openai")
    except Exception as e:
        log.warning("vector_store_init_failed", error=str(e)[:100])
        vector_store = None

    # Expose vector store to knowledge routes + memory tools + openclaw connector
    set_vector_store(vector_store)
    set_memory_vector_store(vector_store)
    set_swarm_instances(hierarchical_swarm, flat_swarm, claude_runner, vector_store)
    log.info("openclaw_connector_initialized", claude=claude_runner is not None, vector_store=vector_store is not None)

    # Register vault memory tools (memory_recall, memory_save, memory_context)
    register_vault_memory_tools(claude_runner.registry if claude_runner else ToolRegistry())

    # Bulk sync vault to Redis for fast cross-session memory retrieval
    try:
        synced = await memory_bridge.bulk_sync_vault_to_redis()
        log.info("vault_redis_sync_complete", entries=synced)
    except Exception as e:
        log.warning("vault_redis_sync_failed", error=str(e)[:100])

    # Start file watcher for vault changes
    try:
        file_watcher = VaultFileWatcher(
            vault_path=vault.root,
            vector_store=vector_store,
            graph_invalidator=lambda: graph_builder.invalidate_cache(),
        )
        file_watcher.start()
        log.info("file_watcher_started")
    except Exception as e:
        log.warning("file_watcher_init_failed", error=str(e)[:100])
        file_watcher = None

    # Load oil & gas agent teams if enabled
    if os.getenv("ENABLE_OILGAS_TEAMS", "true").lower() in ("true", "1", "yes"):
        try:
            import nanobot.teams.oilgas_teams  # noqa: F401 — registers teams on import
            log.info("oilgas_teams_loaded")
        except Exception as e:
            log.warning("oilgas_teams_load_failed", error=str(e)[:100])

    # Register oil & gas engineering tools with Claude runner
    if claude_runner:
        for tool in get_oilgas_tools():
            claude_runner.registry.register(tool)
        log.info("oilgas_tools_registered", count=len(get_oilgas_tools()))

    # Start background scheduler with swarm runner
    async def _swarm_runner(goal: str, mode: str, context: dict) -> dict:
        """Scheduler callback — routes to appropriate swarm backend.

        Backend selection:
        1. If a team specifies backend="claude" and Claude is available → use Claude
        2. If backend="auto" and Claude is available → prefer Claude for flat mode
        3. Otherwise → fall back to vLLM swarm
        """
        # Check if the calling team prefers Claude
        team_name = context.pop("_team_name", None) if isinstance(context, dict) else None
        team = get_team(team_name) if team_name else None
        use_claude = False

        if claude_runner:
            if team and team.backend == "claude":
                use_claude = True
            elif team and team.backend == "auto" and mode == "flat":
                use_claude = True
            elif not team and mode == "flat":
                use_claude = True

        if use_claude and claude_runner:
            log.info("swarm_runner_using_claude", team=team_name, mode=mode)
            return await claude_runner.run(goal, mode, context)

        # Fallback to vLLM swarm
        if mode == "hierarchical" and hierarchical_swarm:
            return await hierarchical_swarm.run(goal, context)
        elif flat_swarm:
            return await flat_swarm.run(goal, context)
        return {"success": False, "error": "No swarm available"}

    scheduler.set_swarm_runner(_swarm_runner)
    scheduler.start()
    log.info("background_scheduler_started")

    yield

    # Cleanup
    scheduler.stop()
    if file_watcher:
        file_watcher.stop()
    if vector_store:
        vector_store.save()
    graph_builder.stop()
    await ms_graph.close()
    await close_pool()
    log.info("gateway_shutdown")


app = FastAPI(
    title="OilGas Nanobot Swarm",
    description="Hierarchical AI Agent Swarm for Oil & Gas Engineering — powered by VibeCaaS.com / NeuralQuantum.ai LLC",
    version="2.0.0",
    lifespan=lifespan,
)

# Serve static dashboard files
_STATIC_DIR = Path(__file__).parent.parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Include OpenClaw/Nellie OpenAI-compatible routes
app.include_router(openclaw_router)

# Include knowledge graph + scheduler routes
app.include_router(knowledge_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != GATEWAY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


# ── Request/Response Models ──────────────────────────────────────────────


class SwarmRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=10000)
    mode: str = Field(
        default="hierarchical",
        description="'hierarchical' for 3-tier swarm, 'flat' for simple swarm",
    )
    metadata: dict = Field(default_factory=dict)


class SwarmResponse(BaseModel):
    success: bool
    session_id: str
    goal: str
    plan_summary: str | None = None
    final_answer: str
    subtask_count: int
    results: list[dict]
    session_summary: dict | None = None


# ── Endpoints ────────────────────────────────────────────────────────────


@app.post("/swarm/run", response_model=SwarmResponse)
async def run_swarm(
    request: SwarmRequest,
    _: str = Depends(verify_api_key),
):
    """Dispatch a goal to the nanobot swarm."""
    log.info("swarm_request", goal_preview=request.goal[:80], mode=request.mode)

    if request.mode == "hierarchical":
        if hierarchical_swarm is None:
            raise HTTPException(503, "Hierarchical swarm not initialized")
        result = await hierarchical_swarm.run(request.goal, request.metadata)
        results_key = "l1_results" if "l1_results" in result else "subtask_results"
    else:
        if flat_swarm is None:
            raise HTTPException(503, "Flat swarm not initialized")
        result = await flat_swarm.run(request.goal, request.metadata)
        results_key = "subtask_results"

    if not result.get("success"):
        raise HTTPException(500, result.get("error", "Swarm failed"))

    return SwarmResponse(
        success=True,
        session_id=result["session_id"],
        goal=result["goal"],
        plan_summary=result.get("plan_summary"),
        final_answer=result["final_answer"],
        subtask_count=len(result.get(results_key, [])),
        results=result.get(results_key, []),
        session_summary=result.get("session_summary"),
    )


class ClaudeRunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=10000)
    mode: str = Field(default="flat", description="'flat' or 'hierarchical'")
    context: dict = Field(default_factory=dict)


@app.post("/claude/run")
async def run_claude(request: ClaudeRunRequest, _: str = Depends(verify_api_key)):
    """Run a goal directly through the Claude agent executor."""
    if not claude_runner:
        raise HTTPException(503, "Claude runner not available — set ANTHROPIC_API_KEY")
    result = await claude_runner.run(request.goal, request.mode, request.context)
    if not result.get("success"):
        raise HTTPException(500, result.get("error", "Claude run failed"))
    return result


@app.get("/", include_in_schema=False)
async def dashboard():
    """Serve the OilGas Nanobot Swarm web dashboard."""
    index_path = Path(__file__).parent.parent / "static" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"message": "OilGas Nanobot Swarm API", "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "hierarchical_swarm": hierarchical_swarm is not None,
        "flat_swarm": flat_swarm is not None,
        "claude_runner": claude_runner is not None,
    }


@app.get("/sessions")
async def list_sessions(_: str = Depends(verify_api_key)):
    sessions = await state_manager.list_recent_sessions(20)
    return {"sessions": sessions}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, _: str = Depends(verify_api_key)):
    session = await state_manager.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    journal = TaskJournal(session_id)
    tasks = await journal.get_session_tasks(50)
    summary = await journal.get_session_summary()

    return {"session": session, "tasks": tasks, "summary": summary}


@app.get("/swarm/health")
async def swarm_health(_: str = Depends(verify_api_key)):
    return await state_manager.get_swarm_health()


@app.get("/agents")
async def list_agents(_: str = Depends(verify_api_key)):
    return {"agents": await state_manager.get_active_agents()}


@app.get("/swarm/topology")
async def get_topology(_: str = Depends(verify_api_key)):
    """Return the full swarm role hierarchy."""
    pipelines = {
        L1Role.CODER: [
            [L2Role.CODE_PLANNER],
            [L2Role.CODE_WRITER],
            [L2Role.CODE_TESTER, L2Role.CODE_REVIEWER],
        ],
        L1Role.RESEARCHER: [
            [L2Role.WEB_SEARCHER],
            [L2Role.SYNTHESIZER, L2Role.FACT_VERIFIER],
        ],
        L1Role.ANALYST: [
            [L2Role.REASONER],
            [L2Role.CRITIQUER],
            [L2Role.SUMMARIZER],
        ],
        L1Role.VALIDATOR: [
            [L2Role.CORRECTNESS, L2Role.COMPLETENESS],
            [L2Role.SCORER],
        ],
        L1Role.EXECUTOR: [
            [L2Role.ACTION_PLANNER],
            [L2Role.ACTION_RUNNER],
        ],
        L1Role.ARCHITECT: [],
    }

    topology = {}
    for l1 in L1Role:
        pipeline = pipelines.get(l1, [])
        topology[l1.value] = {
            "stages": len(pipeline),
            "pipeline": [[r.value for r in stage] for stage in pipeline],
        }

    return {
        "tiers": 3,
        "l0": "queen",
        "l1_roles": [r.value for r in L1Role],
        "topology": topology,
    }
