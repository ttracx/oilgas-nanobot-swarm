# NeuralQuantum Nanobot Swarm

A hierarchical multi-agent inference system powered by vLLM, designed for autonomous task decomposition and execution. Built for the NeuralQuantum.ai platform, managed by the OpenClaw agent **Nellie**.

## Architecture

```
                    ┌─────────────────────┐
                    │   Nellie (OpenClaw)  │
                    │   Management Layer   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Gateway API :8100  │
                    │  OpenAI-Compatible   │
                    └──────────┬──────────┘
                               │
              ┌────────────────▼────────────────┐
              │         Queen Orchestrator (L0)  │
              │    Decomposes → Assigns → Synth  │
              └────────────────┬────────────────┘
                               │
          ┌──────────┬─────────┼─────────┬──────────┐
          ▼          ▼         ▼         ▼          ▼
     ┌─────────┐ ┌───────┐ ┌────────┐ ┌─────────┐ ┌────────┐
     │ Coder   │ │Rsrchr │ │Analyst │ │Validatr │ │Executr │  L1
     │ Lead    │ │ Lead  │ │  Lead  │ │  Lead   │ │  Lead  │
     └────┬────┘ └───┬───┘ └───┬────┘ └────┬────┘ └───┬────┘
          │          │         │           │          │
     ┌────▼────┐ ┌───▼───┐ ┌──▼───┐ ┌────▼────┐ ┌───▼────┐
     │Planner  │ │Search │ │Reason│ │Correct  │ │Plan    │  L2
     │Writer   │ │Synth  │ │Critic│ │Complete │ │Run     │
     │Tester   │ │Verify │ │Summ  │ │Score    │ │        │
     │Reviewer │ │       │ │      │ │         │ │        │
     └─────────┘ └───────┘ └──────┘ └─────────┘ └────────┘
          │          │         │           │          │
     ┌────▼──────────▼─────────▼───────────▼──────────▼────┐
     │              vLLM Server :8000                       │
     │    GLM-4.7-Flash-Claude-Opus-4.5-Reasoning-Distill   │
     │         RTX 4060 Ti 16GB │ bfloat16 │ 32 seq        │
     └─────────────────────────────────────────────────────┘
          │                                    │
     ┌────▼──────┐                      ┌──────▼──────┐
     │   Redis   │                      │    Tools    │
     │   State   │                      │ Search/Code │
     │  Memory   │                      │ File/HTTP   │
     └───────────┘                      └─────────────┘
```

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | RTX 3060 12GB | RTX 4060 Ti 16GB |
| RAM | 32 GB | 64+ GB |
| Disk | 50 GB free | 100+ GB free |
| CUDA | 12.0+ | 12.4+ |
| Platform | Linux / WSL2 | Linux / WSL2 |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/ttracx/nanobot-swarm.git
cd nanobot-swarm

# 2. Setup environment
uv venv ~/vllm-nanobot-env --python 3.12
source ~/vllm-nanobot-env/bin/activate
uv pip install -e .
uv pip install torch vllm

# 3. Configure
cp .env.example .env
# Edit .env with your settings

# 4. Launch everything
bash scripts/start_all.sh
```

## API Usage

### Dispatch a goal (swarm endpoint)

```bash
curl -X POST http://localhost:8100/swarm/run \
  -H "Content-Type: application/json" \
  -H "x-api-key: nq-gateway-key" \
  -d '{"goal": "Design a REST API for a task management system", "mode": "hierarchical"}'
```

### OpenAI-compatible (for Nellie / any OpenAI client)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8100/v1",
    api_key="nq-gateway-key",
)

response = client.chat.completions.create(
    model="nanobot-swarm-hierarchical",
    messages=[
        {"role": "system", "content": "You are managing nanobot teams for code generation."},
        {"role": "user", "content": "Build a FastAPI CRUD service for a blog with PostgreSQL"},
    ],
)
print(response.choices[0].message.content)
```

### Nellie direct dispatch

```bash
curl -X POST http://localhost:8100/v1/nellie/dispatch \
  -H "Content-Type: application/json" \
  -d '{"task": "Write unit tests for auth module", "team": "coder", "priority": 2}'
```

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/swarm/run` | API key | Run swarm (hierarchical or flat) |
| POST | `/v1/chat/completions` | - | OpenAI-compatible chat |
| POST | `/v1/nellie/dispatch` | - | Direct team dispatch |
| GET | `/v1/nellie/sessions` | - | Nellie's session history |
| GET | `/v1/nellie/health` | - | Swarm health for Nellie |
| GET | `/v1/models` | - | List available models |
| GET | `/health` | - | System health check |
| GET | `/swarm/health` | API key | Detailed swarm health |
| GET | `/swarm/topology` | API key | Full role hierarchy |
| GET | `/sessions` | API key | Recent sessions |
| GET | `/sessions/{id}` | API key | Session detail + tasks |
| GET | `/agents` | API key | Active agent list |
| GET | `/docs` | - | Swagger UI |

## Project Structure

```
nanobot-swarm/
├── nanobot/
│   ├── core/                          # Agent hierarchy
│   │   ├── agent.py                   # Base types, 22 AgentRole enums
│   │   ├── agent_v2.py                # Tool-use agent (agentic loop)
│   │   ├── agent_v3.py                # + Redis state persistence
│   │   ├── orchestrator.py            # Flat swarm orchestrator
│   │   ├── roles.py                   # L0/L1/L2 role taxonomy
│   │   ├── sub_prompts.py             # 15 specialized L2 system prompts
│   │   ├── sub_swarm.py               # Per-L1 mini-swarm pipeline
│   │   ├── l1_agent.py                # L1 domain leads
│   │   └── hierarchical_swarm.py      # 3-tier Queen→L1→L2
│   ├── tools/                         # Agentic tool layer
│   │   ├── base.py                    # ToolRegistry + BaseTool ABC
│   │   ├── router.py                  # Tool-use loop engine
│   │   ├── web_search.py              # DuckDuckGo search
│   │   ├── code_runner.py             # Sandboxed Python execution
│   │   ├── file_io.py                 # Workspace file I/O
│   │   └── http_fetch.py              # URL fetcher
│   ├── state/                         # Redis persistence
│   │   ├── connection.py              # Async pool singleton
│   │   ├── memory_store.py            # Per-agent memory
│   │   ├── task_journal.py            # Audit trail
│   │   └── swarm_state.py             # Global session/agent registry
│   ├── integrations/
│   │   └── openclaw_connector.py      # OpenAI-compat API for Nellie
│   └── api/
│       └── gateway.py                 # FastAPI gateway
├── scripts/
│   ├── start_all.sh                   # Launch Redis→vLLM→Gateway
│   ├── launch_vllm.sh                 # vLLM server (RTX 4060 Ti)
│   ├── launch_redis.sh                # Redis with nanobot config
│   ├── launch_gateway.sh              # Gateway on :8100
│   └── setup_env.sh                   # Initial setup
├── tests/
│   └── test_imports.py                # Import validation
├── docs/
│   ├── ARCHITECTURE.md                # System design deep-dive
│   ├── DEPLOYMENT.md                  # Deployment guide
│   ├── API.md                         # API reference
│   ├── AGENTS.md                      # Agent role reference
│   └── NELLIE_INTEGRATION.md          # OpenClaw integration guide
├── pyproject.toml
├── .env.example
└── .gitignore
```

## Model

**[TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill](https://huggingface.co/TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill)**

- Architecture: GLM-4 MoE Lite
- Base: unsloth/GLM-4.7-Flash
- Training: Distilled from Claude Opus 4.5 high-reasoning outputs
- Size: ~7B params, fits in 16GB VRAM at bfloat16
- License: Apache 2.0

## Performance

| Metric | Expected (RTX 4060 Ti 16GB) |
|--------|----------------------------|
| Model load | ~60-90 seconds |
| First token latency | ~800ms-1.5s |
| Throughput (batch 32) | ~300-500 tok/s |
| Single agent task | ~3-6 seconds |
| 5-agent parallel | ~8-15 seconds |
| VRAM usage | ~12-14 GB |
| Full hierarchical run | ~30-90 seconds |

## License

Private repository. All rights reserved, NeuralQuantum.ai LLC.

## Author

**Tommy Xaypanya** — Chief AI & Quantum Systems Officer, NeuralQuantum.ai
