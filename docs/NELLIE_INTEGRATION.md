# Nellie (OpenClaw) Integration Guide

## Overview

The Nanobot Swarm exposes an OpenAI-compatible API that Nellie can use to delegate tasks to specialized agent teams. From Nellie's perspective, the swarm appears as a model she can call via standard OpenAI client libraries.

## Connection Setup

### In Nellie's configuration

Point Nellie's OpenAI client at the swarm gateway:

```python
from openai import OpenAI

# Nellie's client for nanobot swarm delegation
swarm_client = OpenAI(
    base_url="http://localhost:8100/v1",
    api_key="nq-gateway-key",  # Not validated on /v1 endpoints
)
```

### Available Models

| Model ID | Behavior |
|----------|----------|
| `nanobot-swarm-hierarchical` | Full 3-tier: Queen→L1→L2 (most capable) |
| `nanobot-swarm-flat` | Simple: Queen→agents (faster, less depth) |
| `nanobot-swarm` | Alias for hierarchical |

## Usage Patterns

### Pattern 1: General Task Delegation

Nellie sends a goal as a chat message. The swarm decomposes and executes autonomously.

```python
response = swarm_client.chat.completions.create(
    model="nanobot-swarm-hierarchical",
    messages=[
        {
            "role": "system",
            "content": (
                "You are managing nanobot teams under Nellie's supervision. "
                "Nellie is coordinating a VibeCaaS platform migration. "
                "Focus on production-quality code with tests."
            ),
        },
        {
            "role": "user",
            "content": "Build a FastAPI authentication service with JWT tokens, refresh tokens, and role-based access control. Include tests.",
        },
    ],
)

result = response.choices[0].message.content
# Contains: implementation + test results + code review + execution metadata
```

### Pattern 2: Direct Team Dispatch

Nellie knows which team she wants. Skip the Queen's planning phase.

```python
import httpx

response = httpx.post(
    "http://localhost:8100/v1/nellie/dispatch",
    json={
        "task": "Review this API design for security vulnerabilities and suggest improvements",
        "team": "validator",
        "priority": 1,
        "context": {
            "api_spec": "OpenAPI spec content here...",
        },
    },
)

result = response.json()
print(result["result"])      # Validation report
print(result["team_used"])   # "validator"
```

### Pattern 3: Streaming Responses

For long-running tasks, stream the response:

```python
stream = swarm_client.chat.completions.create(
    model="nanobot-swarm-hierarchical",
    messages=[{"role": "user", "content": "Design a complete CI/CD pipeline for a monorepo"}],
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### Pattern 4: Session Monitoring

Nellie checks on her swarm's activity:

```python
import httpx

# Health check
health = httpx.get("http://localhost:8100/v1/nellie/health").json()
print(f"Status: {health['swarm_status']}")
print(f"Active nanobots: {health['active_nanobots']}")

# Session history
sessions = httpx.get("http://localhost:8100/v1/nellie/sessions").json()
for s in sessions["sessions"]:
    print(f"[{s['status']}] {s['goal'][:60]}")
```

## Response Format

Every swarm response includes execution metadata as a footer:

```
[Final synthesized answer here...]

---
[Swarm Session: abc123] [Tasks: 8] [Success Rate: 100.0%] [Tokens: 12500]
```

Nellie can parse this to track swarm efficiency.

## Team Selection Guide

| Nellie's Need | Team | Why |
|---------------|------|-----|
| Write new code | `coder` | Full pipeline: plan→write→test→review |
| Research a topic | `researcher` | Search→synthesize→verify facts |
| Analyze a decision | `analyst` | Reason→critique→summarize |
| Review output quality | `validator` | Check correctness, completeness, score |
| Execute multi-step plan | `executor` | Plan actions→run them |
| Complex multi-domain task | `auto` | Queen decides team composition |

## Error Handling

If the swarm fails, the response still returns (HTTP 200) with an error prefix:

```
[SWARM ERROR] Could not parse queen plan: ...
```

Nellie should check for `[SWARM ERROR]` prefix in responses to detect failures.

## Architecture from Nellie's Perspective

```
Nellie (OpenClaw Agent)
    │
    │  OpenAI-compatible API calls
    │
    ▼
Gateway :8100
    │
    ├── /v1/chat/completions  → Hierarchical or Flat swarm
    ├── /v1/nellie/dispatch   → Direct team control
    ├── /v1/nellie/sessions   → Session monitoring
    └── /v1/nellie/health     → Swarm health
    │
    ▼
Nanobot Swarm (22 agent roles)
    │
    ▼
vLLM :8000 (GLM-4.7-Flash reasoning model)
```

## Nellie's OpenClaw Orchestrator Config

To register the swarm as a tool in Nellie's orchestrator at `:8770`:

```python
NANOBOT_SWARM_TOOL = {
    "name": "nanobot_swarm",
    "description": "Delegate complex tasks to a hierarchical swarm of 22 specialized AI agents",
    "endpoint": "http://localhost:8100/v1/chat/completions",
    "type": "openai_compatible",
    "model": "nanobot-swarm-hierarchical",
    "capabilities": [
        "code_generation",
        "code_review",
        "research",
        "analysis",
        "validation",
        "execution",
    ],
}
```
