# Deployment Guide

OilGas Nanobot Swarm supports four deployment targets. Choose based on your needs:

| Target | AI Backend | Redis | Scheduler | Best For |
|--------|-----------|-------|-----------|----------|
| **Vercel** | Ollama Cloud + NVIDIA NIM | ❌ | ❌ | Demo, API access |
| **Render** | Ollama/NIM + optional local | ✅ | ✅ | Production |
| **Railway** | Ollama/NIM + optional local | ✅ | ✅ | Production |
| **Docker Compose** | Configurable | ✅ | ✅ | Local development |

---

## Vercel (Live Demo)

**Current deployment**: `https://oilgas-nanobot-swarm.vibecaas.app`

### Critical: `vercel.json` Configuration

Vercel must use the `functions` config (not `builds`). This is the only pattern that works reliably with FastAPI:

```json
{
  "version": 2,
  "functions": {
    "api/index.py": {
      "maxDuration": 60
    }
  },
  "rewrites": [
    { "source": "/", "destination": "/nanobot/static/index.html" },
    { "source": "/health", "destination": "/api/index.py" },
    { "source": "/swarm/:path*", "destination": "/api/index.py" },
    { "source": "/v1/:path*", "destination": "/api/index.py" },
    { "source": "/docs", "destination": "/api/index.py" },
    { "source": "/openapi.json", "destination": "/api/index.py" }
  ]
}
```

**Do NOT use `builds` config** — it causes FUNCTION_INVOCATION_FAILED with FastAPI.

**Do NOT add a `handler` variable** in `api/index.py` — Vercel auto-detects `app`.

### Deploy

```bash
npm i -g vercel
vercel login
vercel --prod
```

### Environment Variables (Vercel Dashboard → Settings → Environment Variables)

| Variable | Required | Description |
|----------|----------|-------------|
| `OLLAMA_API_KEY` | ✅ | Ollama Cloud API key (primary AI, fast ~3-5s) |
| `NVIDIA_API_KEY` | Recommended | NVIDIA NIM fallback |
| `GATEWAY_API_KEY` | Optional | If set, admin endpoints require this key |

### Adding/Updating Env Vars via CLI

```bash
# Add (no trailing newline — critical!)
printf '%s' "your-key-value" | vercel env add OLLAMA_API_KEY production

# Remove and re-add
vercel env rm OLLAMA_API_KEY production --yes
printf '%s' "new-key-value" | vercel env add OLLAMA_API_KEY production
```

> ⚠️ **Always use `printf '%s'`** not `echo` — `echo` adds a newline which breaks auth comparisons.

### Supported Python Versions

Vercel reads the Python version from `pyproject.toml`:
```toml
[project]
requires-python = ">=3.11"
```
Vercel will use Python 3.12. The app is compatible with 3.11+.

### Vercel Function Timeout

Default is 10 seconds on Hobby plan. Set `maxDuration: 60` in `vercel.json` to extend (Pro plan required for > 10s).

---

## Render (Full Stack)

The `render.yaml` provisions a web service, Redis, and persistent disk.

### One-Click Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ttracx/oilgas-nanobot-swarm)

### Manual Deploy

```bash
# Install Render CLI
npm i -g @render/cli

# Deploy
render deploy --config render.yaml
```

### render.yaml Overview

```yaml
services:
  - type: web
    name: oilgas-nanobot-gateway
    runtime: docker
    healthCheckPath: /health
    envVars:
      - key: OLLAMA_API_KEY
        sync: false     # Enter in dashboard
      - key: GATEWAY_API_KEY
        generateValue: true
      - key: REDIS_HOST
        fromService:
          name: oilgas-nanobot-redis
          type: redis
          property: host
  - type: redis
    name: oilgas-nanobot-redis
    plan: starter
```

### Environment Variables (Render Dashboard)

Same as Vercel plus Redis (auto-configured from `fromService`).

---

## Railway (Full Stack)

```bash
npm i -g @railway/cli
railway login
railway link
railway up
```

### Environment Variables (Railway Dashboard)

| Variable | Value |
|----------|-------|
| `OLLAMA_API_KEY` | Your Ollama Cloud key |
| `NVIDIA_API_KEY` | Your NVIDIA NIM key |
| `GATEWAY_API_KEY` | Generate a secure random string |
| `ENABLE_OILGAS_TEAMS` | `true` |
| `REDIS_HOST` | Auto-set by Railway Redis addon |

Railway auto-detects `railway.toml` and provisions Redis if configured.

---

## Docker Compose (Local)

```bash
git clone https://github.com/ttracx/oilgas-nanobot-swarm.git
cd oilgas-nanobot-swarm

# Configure
cp .env.example .env
# Edit .env with your API keys

# Start (includes Redis)
docker compose up -d

# View logs
docker compose logs -f nanobot

# Stop
docker compose down
```

### docker-compose.yml Services

| Service | Port | Purpose |
|---------|------|---------|
| `nanobot` | 8100 | FastAPI gateway |
| `redis` | 6379 | State store + session memory |

### Health Check

```bash
curl http://localhost:8100/health
```

---

## GitHub Codespaces

[![Open in Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ttracx/oilgas-nanobot-swarm?quickstart=1)

The `.devcontainer/devcontainer.json` configures:
- Python 3.11 + all dependencies auto-installed
- Redis started automatically
- Port 8100 forwarded to browser
- VS Code extensions: Python, Docker, REST Client

**Store API keys as Codespaces Secrets** to avoid entering them each session:
> GitHub → Settings → Codespaces → New secret

---

## Environment Variables Reference

```bash
# .env.example

# ── Primary AI (Ollama Cloud) ──────────────────────────────────────────────
OLLAMA_API_KEY=your-ollama-cloud-api-key
# Available models: ministral-3:8b, glm-5, kimi-k2:1t, qwen3-coder:480b

# ── Fallback AI (NVIDIA NIM) ──────────────────────────────────────────────
NVIDIA_API_KEY=nvapi-your-nvidia-key
# Models: meta/llama-3.3-70b-instruct, moonshotai/kimi-k2-instruct-0905

# ── Optional: Anthropic Claude ────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-your-key
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# ── Gateway Auth ──────────────────────────────────────────────────────────
GATEWAY_API_KEY=generate-a-secure-random-key
# If unset: all requests are public (demo mode)

# ── Redis ─────────────────────────────────────────────────────────────────
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

# ── Oil & Gas ─────────────────────────────────────────────────────────────
ENABLE_OILGAS_TEAMS=true
VAULT_PATH=~/.nellie/vault   # optional: Obsidian knowledge vault
```

---

## Common Issues

### `FUNCTION_INVOCATION_FAILED` on Vercel

**Cause**: Using `builds` config instead of `functions` config in `vercel.json`.

**Fix**: Use exactly this vercel.json pattern:
```json
{"version":2,"functions":{"api/index.py":{"maxDuration":60}},"rewrites":[...]}
```

### Auth failures with environment variables

**Cause**: `echo` adds a trailing newline to the key value.

**Fix**: Use `printf '%s' "value"` when setting env vars via CLI.

### Function timeout on Vercel Hobby plan

**Cause**: Hobby plan caps at 10 seconds regardless of `maxDuration`.

**Fix**: Upgrade to Vercel Pro, or use a faster model (`ministral-3:8b` responds in ~3-5s).

### Redis connection refused (local)

```bash
docker run -d -p 6379:6379 redis:7.4-alpine
```

---

## Pro Edition

> **⭐ Pro Edition** includes: dedicated Redis, full hierarchical swarm, knowledge vault, background scheduler, MS 365 integration, multi-tenant support, priority support.
>
> Contact: [info@neuralquantum.ai](mailto:info@neuralquantum.ai)
