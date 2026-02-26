# API Reference

**Base URL**: `https://oilgas-nanobot-swarm.vibecaas.app`
**Swagger UI**: `https://oilgas-nanobot-swarm.vibecaas.app/docs`

All endpoints return JSON. The `/swarm/run` and `/v1/chat/completions` endpoints are **public** — no API key required for demo use.

---

## Endpoints

### `GET /health`

Public health check.

```bash
curl https://oilgas-nanobot-swarm.vibecaas.app/health
```

```json
{
  "status": "ok",
  "service": "OilGas Nanobot Swarm",
  "version": "2.0.0",
  "oilgas_teams": true,
  "demo": true
}
```

---

### `POST /swarm/run`

Dispatch an engineering task. **No API key required.**

**Request:**
```json
{
  "goal": "Calculate ECD at 10,000 ft TVD with 10.5 ppg mud and 320 psi annular pressure loss",
  "mode": "hierarchical",
  "team": "well-engineering-review"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `goal` | string | ✅ | Engineering question or task (max 10,000 chars) |
| `mode` | string | — | `"hierarchical"` (default) or `"flat"` |
| `team` | string | — | Named team from [AGENT_TEAMS.md](AGENT_TEAMS.md) |

**Response:**
```json
{
  "success": true,
  "session_id": "nq-1772088336060",
  "goal": "...",
  "final_answer": "ECD Calculation:\n\nECD = MW + APL / (0.052 × TVD)\n= 10.5 + 320 / (0.052 × 10000)\n= 10.5 + 0.615\n= 11.115 ppg\n\n✅ SAFE — ECD (11.115 ppg) < Fracture Gradient (14.2 ppg)\n\n⚠️ Verify all calculations with a licensed petroleum engineer.",
  "subtask_count": 1,
  "duration_seconds": 7.6,
  "powered_by": "NeuralQuantum.ai"
}
```

**Examples:**

```bash
# ECD calculation
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{"goal": "Calculate ECD at 10,000 ft TVD with 10.5 ppg mud and 320 psi APL"}'

# Named team
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{"goal": "Daily field briefing: 8200 BOPD, 14.5 MMSCFD, 22000 BWPD", "team": "oilgas-field-briefing"}'

# Well control
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{"goal": "Calculate kill mud weight. SIDPP=380 psi, MW=10.5 ppg, TVD=9800 ft"}'
```

---

### `POST /v1/chat/completions`

OpenAI-compatible endpoint. Works with any OpenAI SDK client.

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://oilgas-nanobot-swarm.vibecaas.app/v1",
    api_key="demo",  # any value works
)

response = client.chat.completions.create(
    model="nanobot-swarm",
    messages=[
        {"role": "user", "content": "Explain Vogel's IPR equation and when to use it"}
    ],
)
print(response.choices[0].message.content)
```

**Streaming:**
```python
stream = client.chat.completions.create(
    model="nanobot-swarm",
    messages=[{"role": "user", "content": "Design a frac program for Wolfcamp A"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

---

### `GET /v1/models`

List available models.

```json
{
  "object": "list",
  "data": [
    {"id": "ministral-3:8b", "object": "model", "owned_by": "ollama"},
    {"id": "meta/llama-3.3-70b-instruct", "object": "model", "owned_by": "nvidia"},
    {"id": "nanobot-swarm", "object": "model", "owned_by": "neuralquantum"}
  ]
}
```

---

### `GET /swarm/topology`

Agent hierarchy overview.

```json
{
  "tiers": 3,
  "l0": "queen",
  "l1_roles": ["coder", "researcher", "analyst", "validator", "executor", "architect"]
}
```

### `GET /docs`

Interactive Swagger UI — test all endpoints in the browser.

---

## SDK Examples

### Python (requests)
```python
import requests

r = requests.post(
    "https://oilgas-nanobot-swarm.vibecaas.app/swarm/run",
    json={"goal": "What is the fracture gradient at 12,000 ft with overburden 1.0 psi/ft and Poisson's ratio 0.25?"},
)
print(r.json()["final_answer"])
```

### JavaScript
```javascript
const res = await fetch("https://oilgas-nanobot-swarm.vibecaas.app/swarm/run", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    goal: "Calculate Archie water saturation: Rt=12.5 ohm-m, Rw=0.04, phi=0.22",
  }),
});
const data = await res.json();
console.log(data.final_answer);
```

### TypeScript
```typescript
interface SwarmResponse {
  success: boolean;
  session_id: string;
  final_answer: string;
  duration_seconds: number;
  powered_by: string;
}

const response = await fetch("https://oilgas-nanobot-swarm.vibecaas.app/swarm/run", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ goal: "Design an artificial lift program for a 65% WC well at 2800 psi reservoir pressure" }),
});
const data: SwarmResponse = await response.json();
```

---

## Error Codes

| Status | Error | Meaning |
|--------|-------|---------|
| `503` | Service unavailable | No AI backend configured |
| `502` | Bad gateway | AI backend call failed — retry |
| `504` | Gateway timeout | Query too complex, try shorter goal |
| `422` | Validation error | Invalid request body |

---

## Rate Limits

- **Demo (Vercel)**: Subject to Vercel function invocation limits and Ollama/NVIDIA NIM rate limits
- **Pro Edition**: Dedicated capacity — contact [info@neuralquantum.ai](mailto:info@neuralquantum.ai)
