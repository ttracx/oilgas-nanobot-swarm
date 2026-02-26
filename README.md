<div align="center">

# OilGas Nanobot Swarm

**Hierarchical AI Agent Swarm for Oil & Gas Engineering**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Anthropic Claude](https://img.shields.io/badge/Claude-Sonnet%204.5-blueviolet?logo=anthropic&logoColor=white)](https://anthropic.com)
[![Redis](https://img.shields.io/badge/Redis-7.4-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy with Vercel](https://img.shields.io/badge/Deploy-Vercel-000000?logo=vercel&logoColor=white)](https://vercel.com/new/clone?repository-url=https://github.com/NeuralQuantumAI/oilgas-nanobot-swarm)
[![Open in GitHub Codespaces](https://img.shields.io/badge/Open-Codespaces-181717?logo=github&logoColor=white)](https://codespaces.new/NeuralQuantumAI/oilgas-nanobot-swarm)

*Autonomous multi-agent engineering intelligence for upstream, midstream, and downstream operations*

[**Quick Start**](#-quick-start) · [**Architecture**](#-architecture) · [**Agent Teams**](#-oil--gas-agent-teams) · [**Tools**](#-engineering-tools) · [**Deploy**](#-deployment) · [**API**](#-api-reference)

</div>

---

## Overview

**OilGas Nanobot Swarm** is an open-source, production-ready hierarchical multi-agent system purpose-built for oil and gas engineering workflows. It combines NeuralQuantum's 3-tier swarm orchestration with domain-specific engineering tools, regulatory references, and AI-powered analysis — all accessible via an OpenAI-compatible REST API.

### What It Does

| Domain | Capabilities |
|--------|-------------|
| **Drilling** | ECD, kick tolerance, MAASP, well control kill sheets, casing design |
| **Reservoir** | IPR curves, Vogel, Darcy flow, formation evaluation, water saturation (Archie) |
| **Production** | Productivity index, decline curves, artificial lift selection, nodal analysis |
| **Pipeline** | Pressure drop (Darcy-Weisbach), flow regime, line sizing, erosional velocity |
| **Petrophysics** | Sonic porosity (Wyllie), shale volume (GR), Archie Sw, net pay cutoffs |
| **Well Control** | Kill mud weight, MAASP, driller's method kill schedule |
| **HSE & Regulatory** | API standards, BSEE/BOEM, OSHA PSM (14 elements), EPA emissions |
| **Economics** | AFE preparation, NPV/IRR, break-even price, EUR sensitivity |

### Who It's For

- **Reservoir Engineers** — automated IPR analysis, material balance, decline curves
- **Drilling Engineers** — well planning reviews, ECD/kick tolerance verification
- **Production Engineers** — surveillance, optimization recommendations
- **HSE Professionals** — PSM compliance audits, HAZOP support
- **Operations Teams** — daily field briefings, digital morning reports
- **Technical Managers** — economic screening, capital allocation analysis

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
           ┌───────────▼┐ ┌───▼──┐ ┌▼────┐ ┌▼───────────┐
           │   Coder    │ │Rsrch │ │Anlst│ │  Executor  │  (L1 Leads)
           │  L1 Agent  │ │ L1   │ │ L1  │ │   L1 Agent │
           └──────┬─────┘ └──┬───┘ └──┬──┘ └─────┬──────┘
                  │          │         │           │
          ┌───────▼──────────▼─────────▼───────────▼───────┐
          │              L2 Sub-Agents (15 roles)           │
          │  Code Planner · Writer · Tester · Reviewer      │
          │  Web Searcher · Synthesizer · Fact Verifier     │
          │  Reasoner · Critiquer · Summarizer · Scorer     │
          └─────────────────────┬───────────────────────────┘
                                │
          ┌─────────────────────▼───────────────────────────┐
          │              Engineering Tool Layer              │
          │  reservoir_pressure_calc · drilling_eng_calc    │
          │  production_eng_calc     · pipeline_hydraulics  │
          │  well_control_calc       · formation_eval_calc  │
          │  oilgas_regulatory_ref   · web_search           │
          └─────────────────────────────────────────────────┘
```

### Tier Structure

| Tier | Role | Count | Responsibility |
|------|------|-------|----------------|
| **L0** | Queen Orchestrator | 1 | Strategic decomposition and synthesis |
| **L1** | Domain Leads | 6 | Coder, Researcher, Analyst, Validator, Executor, Architect |
| **L2** | Sub-Agents | 15 | Narrow specialists (planner, writer, tester, searcher, etc.) |

---

## Quick Start

### Option 1 — GitHub Codespaces (Zero Setup)

Launch a fully-configured cloud dev environment instantly:

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/NeuralQuantumAI/oilgas-nanobot-swarm?quickstart=1)

```bash
# Inside the Codespace:
export ANTHROPIC_API_KEY=sk-ant-your-key
python -m uvicorn nanobot.api.gateway:app --reload --port 8100
# → Open http://localhost:8100/docs
```

---

### Option 2 — Local Development

**Prerequisites**: Python 3.11+, Redis 7+

```bash
# 1. Clone
git clone https://github.com/NeuralQuantumAI/oilgas-nanobot-swarm.git
cd oilgas-nanobot-swarm

# 2. Install
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY at minimum

# 4. Start Redis
docker run -d -p 6379:6379 redis:7.4-alpine

# 5. Launch
python -m uvicorn nanobot.api.gateway:app --reload --port 8100
```

---

### Option 3 — Docker Compose

```bash
git clone https://github.com/NeuralQuantumAI/oilgas-nanobot-swarm.git
cd oilgas-nanobot-swarm
echo "ANTHROPIC_API_KEY=sk-ant-your-key" > .env
docker compose up -d
docker compose logs -f nanobot
```

---

## Configuration

```bash
# .env — copy from .env.example

# AI Backend (choose one or both)
ANTHROPIC_API_KEY=sk-ant-your-key-here
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# Optional: local vLLM inference
VLLM_URL=http://localhost:8000/v1
VLLM_API_KEY=your-vllm-api-key

# Gateway auth
GATEWAY_API_KEY=your-secure-api-key

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Oil & Gas features
ENABLE_OILGAS_TEAMS=true
```

---

## Oil & Gas Agent Teams

Pre-configured swarm teams for engineering workflows. Dispatch via API or scheduler.

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

### Example: Run a Well Engineering Review

```bash
curl -X POST http://localhost:8100/swarm/run \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Review well X-1: TD 12,500 ft TVD, MW=10.5 ppg, shoe at 8,200 ft with FG=14.2 ppg. Check ECD, kick tolerance, and MAASP.",
    "team": "well-engineering-review",
    "mode": "hierarchical"
  }'
```

### Example: Daily Field Briefing

```bash
curl -X POST http://localhost:8100/swarm/run \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Generate daily field briefing. Production: 8,200 BOPD, 14.5 MMSCFD gas, 22,000 BWPD. 2 wells shut-in for ESP replacement.",
    "team": "oilgas-field-briefing"
  }'
```

---

## Engineering Tools

Standalone tools available to all agents:

| Tool | Calculates |
|------|-----------|
| `reservoir_pressure_calc` | Hydrostatic gradient, BHP, pore pressure, fracture gradient |
| `drilling_engineering_calc` | ECD, kick tolerance, mud weight window, surge/swab |
| `production_engineering_calc` | PI, Vogel IPR, Darcy flow, artificial lift selection |
| `pipeline_hydraulics_calc` | Pressure drop (D-W), flow regime, line sizing |
| `well_control_calc` | MAASP, kill mud weight, driller's method |
| `formation_evaluation_calc` | Archie Sw, sonic porosity, shale volume (GR) |
| `oilgas_regulatory_reference` | API standards, BSEE, OSHA PSM, EPA emissions |

### Quick Example — ECD Calculation

```bash
curl -X POST http://localhost:8100/swarm/run \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Calculate ECD. Mud weight: 10.5 ppg, annular pressure loss: 350 psi, TVD: 9,800 ft.",
    "mode": "flat"
  }'
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/swarm/run` | Dispatch a hierarchical or flat swarm task |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completions |
| `POST` | `/v1/nellie/dispatch` | Dispatch a named agent team |
| `GET` | `/health` | System health check |
| `GET` | `/swarm/health` | Swarm metrics |
| `GET` | `/sessions` | Recent 10 sessions |
| `GET` | `/sessions/{id}` | Session detail and audit trail |
| `GET` | `/docs` | Interactive Swagger UI |

---

## Deployment

### Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/NeuralQuantumAI/oilgas-nanobot-swarm)

The included `render.yaml` provisions:
- Web service (nanobot gateway) — Starter plan
- Managed Redis — Starter plan
- 5 GB persistent disk for workspace
- Health checks and auto-restarts

```bash
# Or deploy via CLI
render deploy --config render.yaml
```

---

### Deploy to Vercel

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/NeuralQuantumAI/oilgas-nanobot-swarm)

The dashboard (`/`) is served as a static file. The REST API is deployed as a Python serverless function via [Mangum](https://mangum.io/) (FastAPI → ASGI adapter).

> **Note**: Vercel's serverless functions are stateless. Redis-backed session history and background scheduler require Render or Railway for full functionality. The dashboard and core engineering calculation endpoints work fully on Vercel.

```bash
# Install Vercel CLI
npm install -g vercel

# Login and deploy
vercel login
vercel --prod
```

**Required environment variables** (set in Vercel dashboard → Project → Settings → Environment Variables):

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GATEWAY_API_KEY` | Auth key for the API (generate a secure random string) |
| `REDIS_URL` | Upstash Redis URL (for session state — optional) |
| `ENABLE_OILGAS_TEAMS` | `true` |

**Recommended Redis for Vercel**: [Upstash](https://upstash.com) (serverless Redis, free tier available).

The `vercel.json` in this repo configures:
- Static dashboard served from `/`
- FastAPI routes at `/swarm/*`, `/v1/*`, `/health`, `/docs`
- Security headers on all responses
- 1-year cache for static assets

---

### Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/oilgas-nanobot?referralCode=neuralquantum)

```bash
npm install -g @railway/cli
railway login
railway link
railway up
```

Set environment variables in the Railway dashboard:
- `ANTHROPIC_API_KEY`
- `GATEWAY_API_KEY`
- `ENABLE_OILGAS_TEAMS=true`

---

### Open in GitHub Codespaces

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/NeuralQuantumAI/oilgas-nanobot-swarm?quickstart=1)

The `.devcontainer/devcontainer.json` provisions:
- Python 3.11 with all dependencies
- Redis auto-started
- Port 8100 forwarded to browser
- VS Code extensions (Python, Docker, REST Client)

---

## Scheduler — Automated Workflows

Configure recurring runs in `workspace/schedules.json`:

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

```bash
python -m nanobot.scheduler.scheduler
```

---

## Safety Disclaimer

> **ENGINEERING DISCLAIMER**: This system is a decision-support tool for qualified petroleum engineers. All calculations, regulatory references, and recommendations must be verified by licensed engineers before use in operational decisions. This tool does not replace API-certified well control training, IADC WellSharp certification, or compliance with applicable regulations.

---

## Roadmap

- [ ] LAS/DLIS wireline log file import for automated formation evaluation
- [ ] SCADA integration via MQTT/OPC-UA for real-time production data
- [ ] Power BI connector for production dashboards
- [ ] AFE document builder with operator templates
- [ ] EPA Subpart W methane emissions calculator
- [ ] Multilingual support (Arabic, Spanish)

---

## Contributing

```bash
git checkout -b feature/new-engineering-tool
# make changes, add tests
pytest tests/ -v
git push origin feature/new-engineering-tool
# open PR against main
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding standards.

---

## License

MIT License — see [LICENSE](LICENSE).

---

<div align="center">

**Built on the NeuralQuantum Nanobot Swarm platform**

© 2026 OilGas Nanobot Swarm powered by VibeCaaS.com a division of NeuralQuantum.ai LLC. All rights reserved.

</div>
