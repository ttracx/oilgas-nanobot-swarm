<div align="center">

# OilGas Nanobot Swarm

**Hierarchical AI Agent Swarm for Oil & Gas Engineering**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Ollama Cloud](https://img.shields.io/badge/Ollama-Cloud-000000?logo=ollama&logoColor=white)](https://ollama.com)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA-NIM-76b900?logo=nvidia&logoColor=white)](https://build.nvidia.com)
[![Redis](https://img.shields.io/badge/Redis-7.4-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy with Vercel](https://img.shields.io/badge/Deploy-Vercel-000000?logo=vercel&logoColor=white)](https://vercel.com/new/clone?repository-url=https://github.com/ttracx/oilgas-nanobot-swarm)
[![Open in GitHub Codespaces](https://img.shields.io/badge/Open-Codespaces-181717?logo=github&logoColor=white)](https://codespaces.new/ttracx/oilgas-nanobot-swarm)

*Autonomous multi-agent engineering intelligence for upstream, midstream, and downstream operations*

**[Live Demo](https://oilgas-nanobot-swarm.vibecaas.app)** · [Quick Start](#-quick-start) · [Architecture](#-architecture) · [Agent Teams](#-oil--gas-agent-teams) · [Tools](#-engineering-tools) · [Deploy](#-deployment) · [API](#-api-reference) · [Docs](docs/)

</div>

---

## Overview

**OilGas Nanobot Swarm** is an open-source, production-ready hierarchical multi-agent AI system purpose-built for oil and gas engineering. It runs on [Vercel](https://oilgas-nanobot-swarm.vibecaas.app) using Ollama Cloud and NVIDIA NIM as AI backends — no GPU required, no local model downloads.

### Live Deployment

| URL | Status |
|-----|--------|
| [oilgas-nanobot-swarm.vibecaas.app](https://oilgas-nanobot-swarm.vibecaas.app) | Dashboard |
| [oilgas-nanobot-swarm.vibecaas.app/health](https://oilgas-nanobot-swarm.vibecaas.app/health) | Health check |
| [oilgas-nanobot-swarm.vibecaas.app/docs](https://oilgas-nanobot-swarm.vibecaas.app/docs) | Swagger UI |

### What It Does

| Domain | Capabilities |
|--------|-------------|
| **Drilling** | ECD, kick tolerance, MAASP, well control kill sheets, casing design |
| **Reservoir** | IPR/Vogel curves, Darcy flow, formation evaluation, water saturation (Archie) |
| **Production** | Productivity index, decline curves, artificial lift selection |
| **Pipeline** | Pressure drop (Darcy-Weisbach), flow regime, line sizing |
| **Petrophysics** | Sonic porosity (Wyllie), shale volume (GR), Archie Sw, net pay |
| **Well Control** | Kill mud weight, MAASP, driller's method kill schedule |
| **HSE & Regulatory** | API standards, BSEE/BOEM, OSHA PSM (14 elements), EPA emissions |
| **Economics** | AFE preparation, NPV/IRR, break-even price, EUR sensitivity |

---

## Architecture

```
                    ┌─────────────────────────────────┐
                    │      FastAPI Gateway :8100       │
                    │  OpenAI-Compatible REST API      │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │     Queen Orchestrator (L0)      │
                    │  Decomposes goals into L1 tasks  │
                    └──┬──────┬──────┬──────┬─────────┘
                       │      │      │      │
           ┌───────────▼┐ ┌───▼──┐ ┌▼────┐ ┌▼──────────┐
           │   Coder    │ │Rsrch │ │Anlst│ │ Executor  │  (L1)
           └──────┬─────┘ └──┬───┘ └──┬──┘ └─────┬─────┘
                  │          │         │           │
          ┌───────▼──────────▼─────────▼───────────▼──────┐
          │            L2 Sub-Agents (15 roles)            │
          └─────────────────────┬──────────────────────────┘
                                │
          ┌─────────────────────▼──────────────────────────┐
          │              Engineering Tool Layer             │
          │  reservoir_pressure_calc · drilling_eng_calc   │
          │  production_eng_calc     · pipeline_hydraulics │
          │  well_control_calc       · formation_eval_calc  │
          │  oilgas_regulatory_ref   · web_search          │
          └────────────────────────────────────────────────┘
                                │
          ┌─────────────────────▼──────────────────────────┐
          │               AI Backend Layer                  │
          │  Primary:  Ollama Cloud (ministral-3:8b)        │
          │  Fallback: NVIDIA NIM (llama-3.3-70b-instruct)  │
          └────────────────────────────────────────────────┘
```

### Tier Structure

| Tier | Role | Count | Responsibility |
|------|------|-------|----------------|
| **L0** | Queen Orchestrator | 1 | Strategic decomposition and synthesis |
| **L1** | Domain Leads | 6 | Coder, Researcher, Analyst, Validator, Executor, Architect |
| **L2** | Sub-Agents | 15 | Narrow specialists (planner, writer, tester, searcher, etc.) |

### Technology Stack

| Component | Technology |
|-----------|------------|
| API Framework | FastAPI 0.115 |
| Primary AI | Ollama Cloud (`ministral-3:8b`, ~3-5s) |
| Fallback AI | NVIDIA NIM (`meta/llama-3.3-70b-instruct`) |
| State Store | Redis 7.4 (full-stack deployments) |
| Serialization | Pydantic v2 |
| HTTP Client | httpx 0.28 |

---

## Quick Start

### Option 1 — Vercel (Zero Setup, Live Now)

The app is already deployed. Grab the API key and start querying:

```bash
# Health check
curl https://oilgas-nanobot-swarm.vibecaas.app/health

# Engineering query (requires x-api-key header)
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_GATEWAY_KEY" \
  -d '{"goal": "Calculate ECD at 10,000 ft TVD with 10.5 ppg mud and 320 psi APL"}'
```

### Option 2 — GitHub Codespaces

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ttracx/oilgas-nanobot-swarm?quickstart=1)

```bash
# Inside Codespace — set env vars and start
export OLLAMA_API_KEY=your-ollama-key
export GATEWAY_API_KEY=your-gateway-key
python -m uvicorn nanobot.api.gateway:app --reload --port 8100
```

### Option 3 — Local Docker Compose

```bash
git clone https://github.com/ttracx/oilgas-nanobot-swarm.git
cd oilgas-nanobot-swarm

# Configure
cp .env.example .env
# Edit .env — add OLLAMA_API_KEY and GATEWAY_API_KEY

# Start (includes Redis)
docker compose up -d
```

### Option 4 — Local Python

```bash
git clone https://github.com/ttracx/oilgas-nanobot-swarm.git
cd oilgas-nanobot-swarm
pip install -e ".[dev]"
cp .env.example .env   # configure OLLAMA_API_KEY
docker run -d -p 6379:6379 redis:7.4-alpine
python -m uvicorn nanobot.api.gateway:app --reload --port 8100
```

---

## Configuration

```bash
# .env — copy from .env.example

# ── Primary AI Backend ─────────────────────────────────────────────────────────
# Ollama Cloud (recommended — fast, cost-effective)
OLLAMA_API_KEY=your-ollama-key
# Models available: ministral-3:8b, glm-5, kimi-k2:1t, qwen3-coder:480b, etc.

# ── Fallback AI Backend ────────────────────────────────────────────────────────
# NVIDIA NIM (high quality, robust fallback)
NVIDIA_API_KEY=nvapi-your-key
# Models: meta/llama-3.3-70b-instruct, moonshotai/kimi-k2-instruct-0905

# ── Optional: Anthropic Claude ────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-your-key
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# ── Gateway ────────────────────────────────────────────────────────────────────
GATEWAY_API_KEY=your-secure-api-key

# ── Redis State Store ──────────────────────────────────────────────────────────
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# ── Oil & Gas Features ─────────────────────────────────────────────────────────
ENABLE_OILGAS_TEAMS=true
```

---

## Oil & Gas Agent Teams

| Team | Mode | Use Case |
|------|------|----------|
| `well-engineering-review` | Hierarchical | Casing design, ECD, kick tolerance, regulatory |
| `reservoir-analysis` | Hierarchical | IPR curves, Sw, formation eval, reserve estimate |
| `drilling-ops-daily` | Flat | Daily report, NPT tracking, cost per foot |
| `production-optimization` | Hierarchical | AI lift, decline curves, waterflood analysis |
| `pipeline-integrity` | Hierarchical | Corrosion, ILI review, MAOP verification |
| `hse-compliance-audit` | Hierarchical | PSM 14-element audit, HAZOP, well integrity |
| `well-economics` | Hierarchical | AFE, NPV/IRR, break-even, EUR sensitivity |
| `oilgas-field-briefing` | Flat | Daily ops briefing, production summary, safety |
| `completions-design` | Hierarchical | Frac design, stage spacing, proppant selection |

### Example: Well Engineering Review

```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "x-api-key: $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Review well X-1: TD 12,500 ft TVD, MW=10.5 ppg, shoe at 8,200 ft with FG=14.2 ppg. Check ECD, kick tolerance, and MAASP.",
    "team": "well-engineering-review",
    "mode": "hierarchical"
  }'
```

### Example: Daily Field Briefing

```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "x-api-key: $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Generate daily field briefing. Production: 8,200 BOPD, 14.5 MMSCFD gas, 22,000 BWPD. 2 wells shut-in for ESP replacement.",
    "team": "oilgas-field-briefing"
  }'
```

---

## Engineering Tools

| Tool | Calculates |
|------|-----------|
| `reservoir_pressure_calc` | Hydrostatic gradient, BHP, pore pressure, fracture gradient |
| `drilling_engineering_calc` | ECD, kick tolerance, mud weight window, surge/swab |
| `production_engineering_calc` | PI, Vogel IPR, Darcy flow, artificial lift selection |
| `pipeline_hydraulics_calc` | Pressure drop (D-W), flow regime, line sizing |
| `well_control_calc` | MAASP, kill mud weight, driller's method |
| `formation_evaluation_calc` | Archie Sw, Wyllie sonic porosity, GR shale volume |
| `oilgas_regulatory_reference` | API standards, BSEE, OSHA PSM, EPA emissions |

---

## API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | — | System health check |
| `GET` | `/` | — | Web dashboard |
| `GET` | `/docs` | — | Interactive Swagger UI |
| `POST` | `/swarm/run` | API key | Dispatch an engineering task |
| `POST` | `/v1/chat/completions` | — | OpenAI-compatible chat |
| `GET` | `/v1/models` | — | List available models |
| `GET` | `/swarm/health` | — | Swarm status |
| `GET` | `/swarm/topology` | — | Agent hierarchy |

### `/swarm/run` Request

```json
{
  "goal": "Your engineering question or task",
  "mode": "hierarchical",
  "team": "optional-team-name",
  "metadata": {}
}
```

### `/swarm/run` Response

```json
{
  "success": true,
  "session_id": "vercel-1234567890",
  "goal": "...",
  "final_answer": "Full engineering analysis with calculations...",
  "subtask_count": 1,
  "duration_seconds": 7.6,
  "mode": "vercel-serverless",
  "model": "ministral-3:8b"
}
```

---

## Deployment

### Deploy to Vercel

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/ttracx/oilgas-nanobot-swarm)

```bash
npm i -g vercel
vercel login
vercel --prod
```

**Required environment variables in Vercel dashboard:**

| Variable | Description |
|----------|-------------|
| `OLLAMA_API_KEY` | Ollama Cloud API key (primary AI) |
| `NVIDIA_API_KEY` | NVIDIA NIM API key (fallback AI) |
| `GATEWAY_API_KEY` | Auth key for `/swarm/run` |

---

### Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ttracx/oilgas-nanobot-swarm)

The `render.yaml` provisions: web service + managed Redis + 5 GB disk.

---

### Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/oilgas-nanobot)

```bash
npm i -g @railway/cli && railway login && railway up
```

---

### Open in GitHub Codespaces

[![Open in Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ttracx/oilgas-nanobot-swarm?quickstart=1)

---

## Scheduled Workflows

Configure recurring agent team runs in `workspace/schedules.json`:

```json
[
  {
    "name": "daily-field-briefing",
    "team": "oilgas-field-briefing",
    "goal": "Generate the 7am daily field operations briefing.",
    "schedule": "07:00",
    "enabled": true
  },
  {
    "name": "weekly-production-review",
    "team": "production-optimization",
    "goal": "Analyze production performance for all wells over the past 7 days.",
    "schedule": "monday 08:00",
    "enabled": true
  }
]
```

Start the scheduler: `python -m nanobot.scheduler.scheduler`

---

## Project Structure

```
oilgas-nanobot-swarm/
├── api/
│   ├── index.py            # Vercel serverless entry (Ollama + NVIDIA NIM)
│   └── requirements.txt    # Slim deps for Vercel function
├── nanobot/
│   ├── core/               # Agent hierarchy (Queen L0, L1 leads, L2 sub-agents)
│   ├── tools/
│   │   ├── oilgas_tools.py     ← 7 engineering calculators
│   │   ├── web_search.py
│   │   └── code_runner.py
│   ├── teams/
│   │   └── oilgas_teams.py     ← 9 pre-configured O&G agent teams
│   ├── scheduler/          # Background job scheduler
│   ├── knowledge/          # Markdown vault (Obsidian-compatible)
│   ├── state/              # Redis persistence
│   ├── integrations/       # External services (MS Graph, OpenClaw)
│   ├── api/                # FastAPI gateway (full-stack mode)
│   └── static/
│       └── index.html      # NeuralQuantum-branded web dashboard
├── docs/                   # Comprehensive documentation
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── AGENTS.md
│   ├── DEPLOYMENT.md
│   ├── ENGINEERING_TOOLS.md
│   ├── AGENT_TEAMS.md
│   └── DEVELOPMENT.md
├── scripts/                # Setup and launch scripts
├── .devcontainer/          # GitHub Codespaces config
├── docker-compose.yml      # Local dev stack (gateway + Redis)
├── Dockerfile              # Production container
├── render.yaml             # Render deployment
├── railway.toml            # Railway deployment
├── vercel.json             # Vercel deployment
└── pyproject.toml
```

---

## Safety Disclaimer

> **⚠️ ENGINEERING DISCLAIMER**: This system is a decision-support tool for qualified petroleum engineers. All calculations, regulatory references, and recommendations must be verified by licensed engineers before use in operational decisions.

---

## Pro Edition

> **⭐ Pro Edition Coming Soon** — Full hierarchical swarm, Redis memory, knowledge vault, background scheduler, MS 365 integration, and priority support.
>
> Contact: [info@neuralquantum.ai](mailto:info@neuralquantum.ai)

---

## Contributing

```bash
git checkout -b feature/my-tool
# implement, add tests
pytest tests/ -v
git push && open PR
```

---

## License

MIT License — see [LICENSE](LICENSE).

---

<div align="center">

**Powered by [VibeCaaS.com](https://vibecaas.com) · a division of [NeuralQuantum.ai LLC](https://neuralquantum.ai)**

© 2026 OilGas Nanobot Swarm powered by VibeCaaS.com a division of NeuralQuantum.ai LLC. All rights reserved.

</div>
