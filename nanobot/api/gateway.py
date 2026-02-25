"""
NeuralQuantum Nanobot Swarm Gateway
REST API for external systems (including OpenClaw/Nellie) to dispatch goals.
"""

import os
import structlog
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nanobot.core.hierarchical_swarm import HierarchicalSwarm
from nanobot.core.orchestrator import NanobotSwarm
from nanobot.core.roles import L1Role, L2Role
from nanobot.state.swarm_state import SwarmStateManager
from nanobot.state.task_journal import TaskJournal
from nanobot.state.connection import close_pool
from nanobot.integrations.openclaw_connector import router as openclaw_router, set_swarm_instances
from nanobot.api.knowledge_routes import router as knowledge_router
from nanobot.knowledge.graph_builder import graph_builder
from nanobot.scheduler.scheduler import scheduler
from nanobot.tools.knowledge_tools import register_knowledge_tools
from nanobot.tools.msgraph_tools import register_msgraph_tools
from nanobot.tools.base import ToolRegistry
from nanobot.integrations.microsoft_graph import ms_graph

log = structlog.get_logger()

GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "nq-gateway-key")
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "nq-nanobot")
WARMUP_MODEL = os.getenv("WARMUP_MODEL", "")  # e.g. "qwen3-coder-next" — empty to skip

hierarchical_swarm: HierarchicalSwarm | None = None
flat_swarm: NanobotSwarm | None = None
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
    global hierarchical_swarm, flat_swarm
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
    set_swarm_instances(hierarchical_swarm, flat_swarm)

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

    # Start background scheduler with swarm runner
    async def _swarm_runner(goal: str, mode: str, context: dict) -> dict:
        """Scheduler callback — routes to appropriate swarm."""
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
    graph_builder.stop()
    await ms_graph.close()
    await close_pool()
    log.info("gateway_shutdown")


app = FastAPI(
    title="NeuralQuantum Nanobot Swarm Gateway",
    version="2.0.0",
    lifespan=lifespan,
)

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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "hierarchical_swarm": hierarchical_swarm is not None,
        "flat_swarm": flat_swarm is not None,
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
