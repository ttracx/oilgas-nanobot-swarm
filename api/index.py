"""
Vercel serverless entry point — OilGas Nanobot Swarm.

Lightweight FastAPI app for Vercel's stateless serverless runtime.
No Redis, no vault, no scheduler, no vLLM — NVIDIA NIM (Kimi K2) model.
For the full stack use Render or Railway.
"""

import os
import time
import json

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────
NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY", "")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")
NIM_BASE_URL    = "https://integrate.api.nvidia.com/v1"
NIM_MODEL       = "moonshotai/kimi-k2-instruct-0905"

app = FastAPI(
    title="OilGas Nanobot Swarm",
    description=(
        "Hierarchical AI Agent Swarm for Oil & Gas Engineering — "
        "powered by VibeCaaS.com / NeuralQuantum.ai LLC\n\n"
        "**Vercel deployment**: Stateless serverless mode (NVIDIA NIM / Kimi K2). "
        "For full stack (Redis, vault, scheduler) deploy to Render or Railway."
    ),
    version="2.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OG_SYSTEM = """You are OilGas Nanobot Swarm, an expert hierarchical AI engineering assistant
for the oil and gas industry built on NeuralQuantum.ai technology.

You have deep expertise across:
UPSTREAM: Reservoir engineering (IPR, Vogel, Darcy flow, Archie Sw, Wyllie porosity),
drilling engineering (ECD, kick tolerance, MAASP, fracture gradient), well control
(kill mud weight, driller method), completions (hydraulic fracturing, stage design).
MIDSTREAM: Pipeline hydraulics (Darcy-Weisbach, Reynolds number, line sizing, erosional velocity).
HSE & REGULATORY: OSHA PSM 14 elements, API standards, BSEE/BOEM, EPA Quad O, NORSOK D-010.
ECONOMICS: AFE, NPV10/IRR, break-even, Arps decline, EUR estimation.

For every engineering calculation: show equation, inputs with units, step-by-step calc, result.
End with: Warning - Verify all calculations with a licensed petroleum engineer before operations.

Powered by VibeCaaS.com, a division of NeuralQuantum.ai LLC."""


def _auth(key: str | None) -> None:
    if GATEWAY_API_KEY and key != GATEWAY_API_KEY:
        raise HTTPException(401, "Invalid or missing API key. Pass as x-api-key header.")


async def _nim_complete(messages: list[dict], stream: bool = False, max_tokens: int = 4096) -> dict | httpx.Response:
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_MODEL,
        "messages": messages,
        "temperature": 0.6,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if stream:
        return payload, headers
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{NIM_BASE_URL}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


class SwarmRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=10_000)
    mode: str = "hierarchical"
    team: str | None = None
    metadata: dict = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = NIM_MODEL
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int = 4096
    temperature: float = 0.6


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "vercel-serverless",
        "model": NIM_MODEL,
        "backend": "NVIDIA NIM",
        "nim_configured": bool(NVIDIA_API_KEY),
        "oilgas_teams": True,
        "note": "Stateless mode — Redis/vault/scheduler not available on Vercel",
    }


@app.post("/swarm/run")
async def run_swarm(req: SwarmRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    if not NVIDIA_API_KEY:
        raise HTTPException(503, "NVIDIA_API_KEY not configured")

    team_ctx = f"\n\nRequested team: {req.team}" if req.team else ""
    messages = [
        {"role": "system", "content": OG_SYSTEM},
        {"role": "user", "content": req.goal + team_ctx},
    ]
    t0 = time.time()
    try:
        data = await _nim_complete(messages, stream=False, max_tokens=8192)
        answer = data["choices"][0]["message"]["content"]
    except Exception as e:
        raise HTTPException(502, f"NIM API error: {str(e)[:200]}")

    return {
        "success": True,
        "session_id": f"vercel-{int(t0 * 1000)}",
        "goal": req.goal,
        "final_answer": answer,
        "subtask_count": 1,
        "results": [{"role": "assistant", "content": answer}],
        "duration_seconds": round(time.time() - t0, 2),
        "mode": "vercel-serverless",
        "model": NIM_MODEL,
    }


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    if not NVIDIA_API_KEY:
        raise HTTPException(503, "NVIDIA_API_KEY not configured")

    msgs = [{"role": "system", "content": OG_SYSTEM}]
    msgs += [{"role": m.role, "content": m.content} for m in req.messages]
    t0 = time.time()

    if req.stream:
        payload, hdrs = await _nim_complete(msgs, stream=True, max_tokens=req.max_tokens)

        async def _gen():
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{NIM_BASE_URL}/chat/completions",
                                          json=payload, headers=hdrs) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            yield (line + "\n\n").encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream")

    data = await _nim_complete(msgs, stream=False, max_tokens=req.max_tokens)
    return {
        "id": f"chatcmpl-{int(t0 * 1000)}",
        "object": "chat.completion",
        "model": NIM_MODEL,
        "choices": data.get("choices", []),
        "usage": data.get("usage", {}),
    }


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [
        {"id": NIM_MODEL, "object": "model", "owned_by": "moonshotai"},
        {"id": "nanobot-swarm", "object": "model", "owned_by": "neuralquantum"},
    ]}


@app.get("/swarm/health")
async def swarm_health():
    return {"status": "ok", "mode": "vercel-serverless", "nim_configured": bool(NVIDIA_API_KEY)}


@app.get("/swarm/topology")
async def topology():
    return {"tiers": 3, "l0": "queen",
            "l1_roles": ["coder", "researcher", "analyst", "validator", "executor", "architect"]}


# Vercel @vercel/python detects `app` (ASGI) or `handler` automatically
handler = app
