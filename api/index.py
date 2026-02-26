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
from mangum import Mangum

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


def _auth(key: str | None) -> None:
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
    return {
        "status": "ok",
        "mode": "vercel-serverless",
        "primary": f"Ollama Cloud ({OLLAMA_MODEL})",
        "fallback": f"NVIDIA NIM ({NIM_MODEL})",
        "ollama_ok": bool(OLLAMA_API_KEY),
        "nim_ok": bool(NVIDIA_API_KEY),
        "oilgas_teams": True,
    }


@app.post("/swarm/run")
async def run_swarm(req: SwarmRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    msgs = [{"role": "system", "content": OG_SYSTEM},
            {"role": "user", "content": req.goal + (f"\nTeam: {req.team}" if req.team else "")}]
    t0 = time.time()
    answer, model = await _chat(msgs)
    return {
        "success": True,
        "session_id": f"vercel-{int(t0 * 1000)}",
        "goal": req.goal,
        "final_answer": answer,
        "subtask_count": 1,
        "results": [{"role": "assistant", "content": answer}],
        "duration_seconds": round(time.time() - t0, 2),
        "mode": "vercel-serverless",
        "model": model,
    }


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    msgs = [{"role": "system", "content": OG_SYSTEM}]
    msgs += [{"role": m.role, "content": m.content} for m in req.messages]
    t0 = time.time()
    answer, model = await _chat(msgs, req.max_tokens)
    return {
        "id": f"chatcmpl-{int(t0 * 1000)}",
        "object": "chat.completion",
        "model": model,
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


# Mangum wraps ASGI for Vercel @vercel/python runtime
handler = Mangum(app, lifespan="auto")
