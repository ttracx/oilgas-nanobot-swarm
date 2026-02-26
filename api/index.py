"""
Vercel serverless entry point — OilGas Nanobot Swarm.

Lightweight FastAPI app for Vercel's stateless serverless runtime.
Primary: Ollama Cloud (ministral-3:8b, fast ~3s)
Fallback: NVIDIA NIM (meta/llama-3.3-70b-instruct)
Full stack (Redis, vault, scheduler): deploy to Render or Railway.
"""

import os
import time

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from mangum import Mangum

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_API_KEY  = os.getenv("OLLAMA_API_KEY", "").strip()
NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY", "").strip()
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "").strip()

# Ollama Cloud — OpenAI-compatible, fast models
OLLAMA_BASE_URL = "https://ollama.com/v1"
OLLAMA_MODEL    = "ministral-3:8b"        # 3–5 s, good quality

# NVIDIA NIM fallback
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_MODEL    = "meta/llama-3.3-70b-instruct"

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="OilGas Nanobot Swarm",
    description=(
        "Hierarchical AI Agent Swarm for Oil & Gas Engineering — "
        "powered by VibeCaaS.com / NeuralQuantum.ai LLC\n\n"
        "Stateless Vercel deployment using Ollama Cloud (ministral-3:8b). "
        "For full stack (Redis, vault, scheduler) deploy to Render or Railway."
    ),
    version="2.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OG_SYSTEM = """You are OilGas Nanobot Swarm, an expert AI engineering assistant
for the oil and gas industry, powered by NeuralQuantum.ai technology.

Deep expertise across:
UPSTREAM: Reservoir engineering (IPR/Vogel, Darcy flow, Archie Sw, Wyllie porosity),
drilling (ECD, kick tolerance, MAASP, fracture gradient via Hubbert & Willis),
well control (kill mud weight, driller method), completions (frac design, stage spacing).
MIDSTREAM: Pipeline hydraulics (Darcy-Weisbach, Reynolds number, line sizing, API 14E erosion).
HSE & REGULATORY: OSHA PSM 14 elements, API 6A/16A/570/650, BSEE/BOEM, EPA Quad O, NORSOK D-010.
ECONOMICS: AFE, NPV10/IRR, break-even price, Arps decline, EUR estimation.

For engineering calculations: state equation + reference, all inputs with units,
step-by-step calculation, result with units, safety/regulatory notes.

End responses with: ⚠️ Verify all calculations with a licensed petroleum engineer.

Powered by VibeCaaS.com, a division of NeuralQuantum.ai LLC."""


def _ollama() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key=OLLAMA_API_KEY or "ollama", timeout=50.0)


def _nim() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=NIM_BASE_URL, api_key=NVIDIA_API_KEY, timeout=50.0)


def _auth(key: str | None) -> None:
    if GATEWAY_API_KEY and key != GATEWAY_API_KEY:
        raise HTTPException(401, "Invalid or missing API key. Pass as x-api-key header.")


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
    temperature: float = 0.6


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _complete(messages: list[dict], max_tokens: int = 4096) -> tuple[str, str]:
    """Try Ollama Cloud first, fall back to NVIDIA NIM. Returns (answer, model_used)."""

    # Primary: Ollama Cloud
    if OLLAMA_API_KEY:
        try:
            resp = await _ollama().chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                temperature=0.6,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or "", OLLAMA_MODEL
        except Exception:
            pass  # fall through to NIM

    # Fallback: NVIDIA NIM
    if NVIDIA_API_KEY:
        try:
            resp = await _nim().chat.completions.create(
                model=NIM_MODEL,
                messages=messages,
                temperature=0.6,
                top_p=0.9,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or "", NIM_MODEL
        except Exception as e:
            raise HTTPException(502, f"All backends failed: {str(e)[:200]}")

    raise HTTPException(503, "No AI backend configured. Set OLLAMA_API_KEY or NVIDIA_API_KEY.")


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "vercel-serverless",
        "primary_model": OLLAMA_MODEL,
        "primary_backend": "Ollama Cloud",
        "fallback_model": NIM_MODEL,
        "ollama_configured": bool(OLLAMA_API_KEY),
        "nim_configured": bool(NVIDIA_API_KEY),
        "oilgas_teams": True,
    }


@app.post("/swarm/run")
async def run_swarm(req: SwarmRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)

    team_ctx = f"\n\nRequested team: {req.team}" if req.team else ""
    messages = [
        {"role": "system", "content": OG_SYSTEM},
        {"role": "user", "content": req.goal + team_ctx},
    ]
    t0 = time.time()
    answer, used_model = await _complete(messages, max_tokens=4096)

    return {
        "success": True,
        "session_id": f"vercel-{int(t0 * 1000)}",
        "goal": req.goal,
        "final_answer": answer,
        "subtask_count": 1,
        "results": [{"role": "assistant", "content": answer}],
        "duration_seconds": round(time.time() - t0, 2),
        "mode": "vercel-serverless",
        "model": used_model,
    }


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    msgs = [{"role": "system", "content": OG_SYSTEM}]
    msgs += [{"role": m.role, "content": m.content} for m in req.messages]

    if req.stream and OLLAMA_API_KEY:
        async def _gen():
            stream = await _ollama().chat.completions.create(
                model=OLLAMA_MODEL, messages=msgs,
                temperature=req.temperature, max_tokens=req.max_tokens, stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield f"data: {chunk.model_dump_json()}\n\n".encode()
            yield b"data: [DONE]\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream")

    t0 = time.time()
    answer, used_model = await _complete(msgs, max_tokens=req.max_tokens)
    return {
        "id": f"chatcmpl-{int(t0 * 1000)}",
        "object": "chat.completion",
        "model": used_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        "usage": {},
    }


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [
        {"id": OLLAMA_MODEL,  "object": "model", "owned_by": "ollama"},
        {"id": NIM_MODEL,     "object": "model", "owned_by": "nvidia"},
        {"id": "nanobot-swarm", "object": "model", "owned_by": "neuralquantum"},
    ]}


@app.get("/swarm/health")
async def swarm_health():
    return {
        "status": "ok",
        "mode": "vercel-serverless",
        "ollama": bool(OLLAMA_API_KEY),
        "nim": bool(NVIDIA_API_KEY),
    }


@app.get("/swarm/topology")
async def topology():
    return {"tiers": 3, "l0": "queen",
            "l1_roles": ["coder", "researcher", "analyst", "validator", "executor", "architect"]}


# Mangum wraps FastAPI ASGI app for Vercel's serverless runtime
handler = Mangum(app, lifespan="off")
