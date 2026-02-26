"""
Vercel serverless entry point — OilGas Nanobot Swarm.

Lightweight FastAPI app for Vercel's stateless serverless runtime.
Model: z-ai/glm5 via NVIDIA NIM (with extended thinking).
For full stack (Redis, vault, scheduler) deploy to Render or Railway.
"""

import os
import time

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────
NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY", "").strip()
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "").strip()
NIM_BASE_URL    = "https://integrate.api.nvidia.com/v1"
NIM_MODEL       = "z-ai/glm5"

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="OilGas Nanobot Swarm",
    description=(
        "Hierarchical AI Agent Swarm for Oil & Gas Engineering — "
        "powered by VibeCaaS.com / NeuralQuantum.ai LLC\n\n"
        "Stateless Vercel deployment using z-ai/glm5 via NVIDIA NIM. "
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

For engineering calculations: state equation + reference, show all inputs with units,
step-by-step calculation, clear result with units, safety/regulatory implications.

End responses with: ⚠️ Verify all calculations with a licensed petroleum engineer.

Powered by VibeCaaS.com, a division of NeuralQuantum.ai LLC."""


def _nim_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=NIM_BASE_URL, api_key=NVIDIA_API_KEY)


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
    model: str = NIM_MODEL
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int = 4096
    temperature: float = 1.0


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "vercel-serverless",
        "model": NIM_MODEL,
        "backend": "NVIDIA NIM",
        "nim_configured": bool(NVIDIA_API_KEY),
        "oilgas_teams": True,
    }


@app.post("/swarm/run")
async def run_swarm(req: SwarmRequest, x_api_key: str | None = Header(default=None)):
    _auth(x_api_key)
    if not NVIDIA_API_KEY:
        raise HTTPException(503, "NVIDIA_API_KEY not configured")

    team_ctx = f"\n\nRequested team: {req.team}" if req.team else ""
    t0 = time.time()

    try:
        client = _nim_client()
        resp = await client.chat.completions.create(
            model=NIM_MODEL,
            messages=[
                {"role": "system", "content": OG_SYSTEM},
                {"role": "user", "content": req.goal + team_ctx},
            ],
            temperature=1.0,
            top_p=1.0,
            max_tokens=8192,
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": True,
                    "clear_thinking": True,
                }
            },
        )
        answer = resp.choices[0].message.content or ""
    except Exception as e:
        raise HTTPException(502, f"NIM API error: {str(e)[:300]}")

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
    client = _nim_client()
    t0 = time.time()

    if req.stream:
        async def _gen():
            stream = await client.chat.completions.create(
                model=NIM_MODEL,
                messages=msgs,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=True,
                extra_body={"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}},
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    data = chunk.model_dump_json()
                    yield f"data: {data}\n\n".encode()
            yield b"data: [DONE]\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream")

    resp = await client.chat.completions.create(
        model=NIM_MODEL,
        messages=msgs,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": True, "clear_thinking": True}},
    )
    return {
        "id": f"chatcmpl-{int(t0 * 1000)}",
        "object": "chat.completion",
        "model": NIM_MODEL,
        "choices": [c.model_dump() for c in resp.choices],
        "usage": resp.usage.model_dump() if resp.usage else {},
    }


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [
        {"id": NIM_MODEL, "object": "model", "owned_by": "z-ai"},
        {"id": "nanobot-swarm", "object": "model", "owned_by": "neuralquantum"},
    ]}


@app.get("/swarm/health")
async def swarm_health():
    return {"status": "ok", "mode": "vercel-serverless", "nim_configured": bool(NVIDIA_API_KEY)}


@app.get("/swarm/topology")
async def topology():
    return {"tiers": 3, "l0": "queen",
            "l1_roles": ["coder", "researcher", "analyst", "validator", "executor", "architect"]}
