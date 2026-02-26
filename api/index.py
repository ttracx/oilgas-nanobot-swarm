"""
Vercel serverless entry point — OilGas Nanobot Swarm.

Lightweight FastAPI app for Vercel's stateless serverless runtime.
No Redis, no vault, no scheduler, no vLLM — Claude API only.
For the full stack use Render or Railway.
"""

import os
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
GATEWAY_API_KEY   = os.getenv("GATEWAY_API_KEY", "")

_client: anthropic.AsyncAnthropic | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    if ANTHROPIC_API_KEY:
        _client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    yield
    if _client:
        await _client.close()


app = FastAPI(
    title="OilGas Nanobot Swarm",
    description=(
        "Hierarchical AI Agent Swarm for Oil & Gas Engineering — "
        "powered by VibeCaaS.com / NeuralQuantum.ai LLC\n\n"
        "**Vercel deployment**: Stateless serverless mode (Claude API). "
        "For full stack (Redis, vault, scheduler, vLLM) deploy to Render or Railway."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_STATIC = Path(__file__).parent.parent / "nanobot" / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

OG_SYSTEM = """You are OilGas Nanobot Swarm, an expert hierarchical AI engineering assistant
for the oil and gas industry. You have deep expertise across:

UPSTREAM: Reservoir engineering (IPR, Vogel, Darcy flow, material balance, Archie Sw,
Wyllie sonic porosity, GR shale volume), drilling engineering (ECD, kick tolerance,
MAASP, fracture gradient via Hubbert & Willis, casing design), well control (kill mud
weight, driller's method), completions (hydraulic fracturing, stage design, proppant selection).

MIDSTREAM: Pipeline hydraulics (Darcy-Weisbach pressure drop, Reynolds number, flow regime,
line sizing, erosional velocity per API 14E), compression, gas processing.

HSE & REGULATORY: OSHA PSM 29 CFR 1910.119 (14 elements), API standards (6A, 16A, 570, 650,
RP 505, RP 14C), BSEE/BOEM offshore regulations, EPA Quad O emissions, NORSOK D-010.

ECONOMICS: AFE preparation, NPV10/IRR, break-even oil price, Arps decline curve analysis,
EUR estimation, capital efficiency (BOE/$ invested).

For every engineering calculation:
1. State the governing equation and reference (e.g., Vogel 1968, Archie 1942)
2. Show all inputs with units
3. Show step-by-step calculation
4. State the result clearly with units
5. Note any safety or regulatory implications

Always end with: "⚠️ Verify all calculations with a licensed petroleum engineer before operations."

Powered by VibeCaaS.com, a division of NeuralQuantum.ai LLC."""


def _auth(key: str | None) -> None:
    if GATEWAY_API_KEY and key != GATEWAY_API_KEY:
        raise HTTPException(401, "Invalid or missing API key. Pass as x-api-key header.")


class SwarmRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=10_000)
    mode: str = "hierarchical"
    team: str | None = None
    metadata: dict = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "nanobot-swarm"
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int = 4096
    temperature: float = 0.1


@app.get("/", include_in_schema=False)
async def dashboard():
    idx = _STATIC / "index.html"
    if idx.exists():
        return FileResponse(str(idx), media_type="text/html")
    return {"message": "OilGas Nanobot Swarm API", "docs": "/docs"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "vercel-serverless",
        "claude_runner": bool(ANTHROPIC_API_KEY),
        "flat_swarm": False,
        "hierarchical_swarm": False,
        "model": ANTHROPIC_MODEL,
        "oilgas_teams": True,
        "note": "Stateless mode — Redis/vault/scheduler not available on Vercel",
    }


@app.post("/swarm/run")
async def run_swarm(req: SwarmRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    if not _client:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    team_ctx = f"\n\nRequested team: {req.team}" if req.team else ""
    t0 = time.time()
    msg = await _client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        system=OG_SYSTEM,
        messages=[{"role": "user", "content": req.goal + team_ctx}],
    )
    answer = msg.content[0].text if msg.content else ""
    return {
        "success": True,
        "session_id": f"vercel-{int(t0 * 1000)}",
        "goal": req.goal,
        "final_answer": answer,
        "subtask_count": 1,
        "results": [{"role": "assistant", "content": answer}],
        "duration_seconds": round(time.time() - t0, 2),
        "mode": "vercel-serverless",
    }


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    if not _client:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    t0 = time.time()

    if req.stream:
        async def _gen():
            async with _client.messages.stream(
                model=ANTHROPIC_MODEL,
                max_tokens=req.max_tokens,
                system=OG_SYSTEM,
                messages=messages,
            ) as s:
                async for text in s.text_stream:
                    payload = (
                        'data: {"id":"chatcmpl","object":"chat.completion.chunk",'
                        '"choices":[{"delta":{"content":' + repr(text) + '},"index":0}]}\n\n'
                    )
                    yield payload.encode()
            yield b"data: [DONE]\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream")

    msg = await _client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=req.max_tokens,
        system=OG_SYSTEM,
        messages=messages,
    )
    answer = msg.content[0].text if msg.content else ""
    return {
        "id": f"chatcmpl-{int(t0 * 1000)}",
        "object": "chat.completion",
        "model": ANTHROPIC_MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": msg.usage.input_tokens, "completion_tokens": msg.usage.output_tokens},
    }


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [
        {"id": "nanobot-swarm", "object": "model", "owned_by": "neuralquantum"},
        {"id": ANTHROPIC_MODEL, "object": "model", "owned_by": "anthropic"},
    ]}


@app.get("/swarm/health")
async def swarm_health():
    return {"status": "ok", "mode": "vercel-serverless", "claude_runner": bool(ANTHROPIC_API_KEY)}


@app.get("/swarm/topology")
async def topology():
    return {"tiers": 3, "l0": "queen",
            "l1_roles": ["coder", "researcher", "analyst", "validator", "executor", "architect"]}


# Vercel @vercel/python has native ASGI support — export `app` directly.
# (Mangum is for AWS Lambda only; not needed on Vercel)
handler = app
