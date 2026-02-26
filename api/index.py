"""
Vercel serverless entry point — OilGas Nanobot Swarm.

Primary:  Ollama Cloud (ministral-3:8b  ~3-5 s)
Fallback: NVIDIA NIM  (meta/llama-3.3-70b-instruct)
Uses httpx directly — no openai SDK dependency.
"""

import os
import time
import json as _json

import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_API_KEY  = os.getenv("OLLAMA_API_KEY", "").strip()
NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY", "").strip()
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "").strip()

OLLAMA_BASE = "https://ollama.com/v1"
OLLAMA_MODEL = "ministral-3:8b"

NIM_BASE  = "https://integrate.api.nvidia.com/v1"
NIM_MODEL = "meta/llama-3.3-70b-instruct"

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="OilGas Nanobot Swarm",
    description=(
        "Hierarchical AI Agent Swarm for Oil & Gas Engineering — "
        "powered by VibeCaaS.com / NeuralQuantum.ai LLC"
    ),
    version="2.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OG_SYSTEM = (
    "You are OilGas Nanobot Swarm, an expert petroleum engineering AI powered by NeuralQuantum.ai. "
    "Expertise: reservoir engineering (IPR/Vogel/Darcy/Archie), drilling (ECD/MAASP/kick tolerance/"
    "fracture gradient), well control (kill mud weight), pipeline hydraulics (Darcy-Weisbach), "
    "completions (frac design), HSE (OSHA PSM, API standards, BSEE, NORSOK D-010), and economics "
    "(AFE/NPV/IRR/EUR). Show equations, all inputs with units, step-by-step calculations, results. "
    "End with: ⚠️ Verify all calculations with a licensed petroleum engineer. "
    "Powered by VibeCaaS.com, a division of NeuralQuantum.ai LLC."
)


def _auth_admin(key: str | None) -> None:
    """Strict auth — used for admin/management endpoints."""
    if GATEWAY_API_KEY and key != GATEWAY_API_KEY:
        raise HTTPException(401, "Invalid or missing API key")


async def _chat(messages: list[dict], max_tokens: int = 4096) -> tuple[str, str]:
    """Call Ollama Cloud, fall back to NVIDIA NIM. Return (answer, model)."""

    async def _post(base: str, key: str, model: str) -> str | None:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=50.0) as client:
                r = await client.post(
                    f"{base}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except Exception:
            return None

    if OLLAMA_API_KEY:
        ans = await _post(OLLAMA_BASE, OLLAMA_API_KEY, OLLAMA_MODEL)
        if ans:
            return ans, OLLAMA_MODEL

    if NVIDIA_API_KEY:
        ans = await _post(NIM_BASE, NVIDIA_API_KEY, NIM_MODEL)
        if ans:
            return ans, NIM_MODEL

    raise HTTPException(503, "No AI backend configured or all backends failed.")


# ── Models ────────────────────────────────────────────────────────────────────
class SwarmRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=10_000)
    mode: str = "hierarchical"
    team: str | None = None
    metadata: dict = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = OLLAMA_MODEL
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int = 4096


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Public health check — does not expose backend details."""
    return {
        "status": "ok",
        "service": "OilGas Nanobot Swarm",
        "version": "2.0.0",
        "oilgas_teams": True,
        "demo": True,
    }


@app.post("/swarm/run")
async def run_swarm(req: SwarmRequest):
    """Public demo endpoint — no API key required. Backend is hidden."""
    msgs = [{"role": "system", "content": OG_SYSTEM},
            {"role": "user", "content": req.goal + (f"\nTeam: {req.team}" if req.team else "")}]
    t0 = time.time()
    answer, _ = await _chat(msgs)  # model name intentionally discarded
    return {
        "success": True,
        "session_id": f"nq-{int(t0 * 1000)}",
        "goal": req.goal,
        "final_answer": answer,
        "subtask_count": 1,
        "results": [{"role": "assistant", "content": answer}],
        "duration_seconds": round(time.time() - t0, 2),
        "powered_by": "NeuralQuantum.ai",
    }


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest):
    """OpenAI-compatible endpoint — public demo."""
    msgs = [{"role": "system", "content": OG_SYSTEM}]
    msgs += [{"role": m.role, "content": m.content} for m in req.messages]
    t0 = time.time()
    answer, _ = await _chat(msgs, req.max_tokens)
    return {
        "id": f"chatcmpl-{int(t0 * 1000)}",
        "object": "chat.completion",
        "model": "nanobot-swarm",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        "usage": {},
    }


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [
        {"id": OLLAMA_MODEL, "object": "model", "owned_by": "ollama"},
        {"id": NIM_MODEL,    "object": "model", "owned_by": "nvidia"},
        {"id": "nanobot-swarm", "object": "model", "owned_by": "neuralquantum"},
    ]}


@app.get("/swarm/health")
async def swarm_health():
    return {"status": "ok", "mode": "vercel-serverless",
            "ollama": bool(OLLAMA_API_KEY), "nim": bool(NVIDIA_API_KEY)}


@app.get("/swarm/topology")
async def topology():
    return {"tiers": 3, "l0": "queen",
            "l1_roles": ["coder", "researcher", "analyst", "validator", "executor", "architect"]}


# ── Agent Builder ──────────────────────────────────────────────────────────────

AGENT_BUILDER_SYSTEM = """You are an expert AI agent architect specializing in oil and gas engineering agents for the NeuralQuantum.ai OilGas Nanobot Swarm platform.

Given a user's description of what they want an agent to do, you MUST respond with ONLY valid JSON — no markdown fences, no explanation, just the raw JSON object.

The JSON must have exactly these fields:
{
  "name": "kebab-case-name",
  "description": "One sentence description for the dashboard",
  "mode": "hierarchical" or "flat",
  "tools": ["list", "of", "tools", "the", "agent", "needs"],
  "system_prompt": "Detailed multi-line system prompt for the agent...",
  "temperature": 0.1,
  "max_tokens": 4096,
  "python_code": "Complete ready-to-paste Python code using register_team(AgentTeam(...))",
  "use_cases": ["Use case 1", "Use case 2", "Use case 3"],
  "example_goal": "A realistic example goal string for this agent"
}

Available tools: reservoir_pressure_calc, drilling_engineering_calc, production_engineering_calc, pipeline_hydraulics_calc, well_control_calc, formation_evaluation_calc, oilgas_regulatory_reference, web_search, code_runner, file_io, http_fetch, knowledge_tools, vault_memory

Rules:
- name: lowercase, hyphens only, descriptive
- mode: "flat" for simple reporting/summaries, "hierarchical" for complex multi-step analysis
- system_prompt: detailed, include workflow steps numbered 1-N, output format section
- temperature: 0.0-0.1 for calculations, 0.2-0.3 for reports
- python_code: must be complete, importable, copy-paste ready"""


TEAM_BUILDER_SYSTEM = """You are an expert AI swarm architect specializing in multi-agent teams for oil and gas engineering on the NeuralQuantum.ai OilGas Nanobot Swarm platform.

Given a user's description, respond with ONLY valid JSON — no markdown fences, no explanation, just the raw JSON object.

The JSON must have exactly these fields:
{
  "name": "kebab-case-team-name",
  "description": "One sentence description",
  "mode": "hierarchical" or "flat",
  "agents": [
    {
      "role": "L1 role name (coder/researcher/analyst/validator/executor/architect)",
      "purpose": "What this agent does in the team",
      "l2_agents": ["list of L2 sub-agent roles if hierarchical"]
    }
  ],
  "orchestration": "Description of how agents coordinate",
  "system_prompt": "Team-level system prompt with full workflow",
  "tools": ["tools", "needed"],
  "temperature": 0.1,
  "max_tokens": 4096,
  "python_code": "Complete register_team(AgentTeam(...)) Python code",
  "schedule_example": "cron expression or interval e.g. '07:00' or '*/6' or 'monday 08:00'",
  "use_cases": ["Use case 1", "Use case 2"],
  "example_goal": "A realistic example goal string"
}

Rules:
- Hierarchical teams: 2-5 L1 agents, each with 2-4 L2 sub-agents
- Flat teams: direct agent execution, best for reporting and summaries
- system_prompt: start with role description, numbered workflow steps, output format
- python_code: complete, importable"""


class BuilderRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000,
                              description="Describe what you want the agent/team to do")


@app.post("/agent/build")
async def build_agent(req: BuilderRequest):
    """Generate a custom agent config from a natural language description."""
    msgs = [
        {"role": "system", "content": AGENT_BUILDER_SYSTEM},
        {"role": "user", "content": f"Create an agent for: {req.description}"},
    ]
    t0 = time.time()
    raw, _ = await _chat(msgs, max_tokens=3000)

    # Strip markdown fences if model added them despite instructions
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        config = _json.loads(text)
    except _json.JSONDecodeError:
        # Try to extract JSON object from text
        import re
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                config = _json.loads(m.group())
            except Exception:
                config = {"raw_output": raw, "parse_error": "Could not parse JSON — copy raw output"}
        else:
            config = {"raw_output": raw, "parse_error": "Could not parse JSON — copy raw output"}

    return {
        "success": True,
        "type": "agent",
        "config": config,
        "duration_seconds": round(time.time() - t0, 2),
        "powered_by": "NeuralQuantum.ai",
    }


@app.post("/team/build")
async def build_team(req: BuilderRequest):
    """Generate a custom agent team config from a natural language description."""
    msgs = [
        {"role": "system", "content": TEAM_BUILDER_SYSTEM},
        {"role": "user", "content": f"Create an agent team for: {req.description}"},
    ]
    t0 = time.time()
    raw, _ = await _chat(msgs, max_tokens=3000)

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        config = _json.loads(text)
    except _json.JSONDecodeError:
        import re
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                config = _json.loads(m.group())
            except Exception:
                config = {"raw_output": raw, "parse_error": "Could not parse JSON — copy raw output"}
        else:
            config = {"raw_output": raw, "parse_error": "Could not parse JSON — copy raw output"}

    return {
        "success": True,
        "type": "team",
        "config": config,
        "duration_seconds": round(time.time() - t0, 2),
        "powered_by": "NeuralQuantum.ai",
    }

