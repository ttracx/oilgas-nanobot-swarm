# API Reference

Base URL: `http://localhost:8100`

## Authentication

Most endpoints require an API key passed as a header:
```
x-api-key: <GATEWAY_API_KEY>
```

OpenAI-compatible endpoints (`/v1/*`) do not require the API key header.

---

## Swarm Endpoints

### POST /swarm/run

Run the nanobot swarm on a goal.

**Request:**
```json
{
  "goal": "Design a microservices architecture for an e-commerce platform",
  "mode": "hierarchical",
  "metadata": {}
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| goal | string | required | The task to accomplish (1-10000 chars) |
| mode | string | "hierarchical" | "hierarchical" (3-tier) or "flat" (simple) |
| metadata | object | {} | Arbitrary metadata passed to session |

**Response:**
```json
{
  "success": true,
  "session_id": "abc123-...",
  "goal": "Design a microservices architecture...",
  "plan_summary": "Break into research, architecture design, and code scaffolding",
  "final_answer": "## Architecture Design\n...",
  "subtask_count": 4,
  "results": [
    {
      "task_id": "t1",
      "l1_role": "researcher",
      "instruction": "Research microservices patterns...",
      "output": "...",
      "success": true
    }
  ],
  "session_summary": {
    "session_id": "abc123-...",
    "total_tasks": 12,
    "successful": 11,
    "failed": 1,
    "success_rate": 91.7,
    "total_tokens": 15420,
    "avg_duration_seconds": 4.2,
    "roles_used": ["orchestrator", "researcher", "coder", "analyst"]
  }
}
```

---

### GET /health

Basic health check.

**Response:**
```json
{
  "status": "ok",
  "hierarchical_swarm": true,
  "flat_swarm": true
}
```

---

### GET /swarm/health

Detailed swarm health with Redis metrics.

**Response:**
```json
{
  "timestamp": 1740000000.0,
  "active_agents": 5,
  "agent_breakdown": {"coder": 2, "researcher": 1, "analyst": 2},
  "recent_sessions": 3,
  "failed_queue_depth": 0,
  "redis_memory_used_mb": 12.4,
  "redis_memory_peak_mb": 45.1,
  "agents": [...]
}
```

---

### GET /swarm/topology

Return the full swarm role hierarchy.

**Response:**
```json
{
  "tiers": 3,
  "l0": "queen",
  "l1_roles": ["coder", "researcher", "analyst", "validator", "executor", "architect"],
  "topology": {
    "coder": {
      "stages": 3,
      "pipeline": [["code_planner"], ["code_writer"], ["code_tester", "code_reviewer"]]
    },
    "researcher": {
      "stages": 2,
      "pipeline": [["web_searcher"], ["synthesizer", "fact_verifier"]]
    }
  }
}
```

---

### GET /sessions

List recent swarm sessions.

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "...",
      "goal": "...",
      "status": "complete",
      "success": true,
      "created_at": 1740000000.0,
      "completed_at": 1740000045.0
    }
  ]
}
```

---

### GET /sessions/{session_id}

Get session detail with all tasks.

**Response:**
```json
{
  "session": { "session_id": "...", "goal": "...", "status": "complete", ... },
  "tasks": [
    {
      "task_id": "...",
      "agent_id": "...",
      "agent_role": "coder",
      "content_preview": "Write a REST API...",
      "status": "complete",
      "success": true,
      "output_preview": "```python\nfrom fastapi...",
      "tokens_used": 1200,
      "duration_seconds": 5.3,
      "tool_calls": ["run_python"]
    }
  ],
  "summary": { ... }
}
```

---

### GET /agents

List all active registered agents.

**Response:**
```json
{
  "agents": [
    {
      "agent_id": "...",
      "role": "coder",
      "name": "coder-lead-a1b2c3",
      "session_id": "...",
      "status": "executing",
      "tasks_completed": 3,
      "tokens_used": 4500
    }
  ]
}
```

---

## OpenAI-Compatible Endpoints

### GET /v1/models

List available swarm models.

**Response:**
```json
{
  "object": "list",
  "data": [
    {"id": "nanobot-swarm-hierarchical", "object": "model", "owned_by": "neuralquantum"},
    {"id": "nanobot-swarm-flat", "object": "model", "owned_by": "neuralquantum"},
    {"id": "nanobot-reasoner", "object": "model", "owned_by": "neuralquantum"}
  ]
}
```

---

### POST /v1/chat/completions

OpenAI-compatible chat completions. Use any OpenAI client library.

**Request:**
```json
{
  "model": "nanobot-swarm-hierarchical",
  "messages": [
    {"role": "system", "content": "Context for the swarm"},
    {"role": "user", "content": "Build a Python CLI for managing tasks"}
  ],
  "temperature": 0.1,
  "max_tokens": 4096,
  "stream": false,
  "metadata": {}
}
```

| Model | Description |
|-------|-------------|
| `nanobot-swarm-hierarchical` | Full 3-tier swarm (Queen→L1→L2) |
| `nanobot-swarm-flat` | Simple flat orchestrator |
| `nanobot-swarm` | Alias for hierarchical |

**Response:**
Standard OpenAI chat completion format with execution metadata appended.

---

## Nellie Management Endpoints

### POST /v1/nellie/dispatch

Direct task dispatch to a specific team.

**Request:**
```json
{
  "task": "Write comprehensive tests for the auth module",
  "team": "coder",
  "priority": 2,
  "context": {"module_path": "src/auth.py"},
  "callback_url": null
}
```

| team | Description |
|------|-------------|
| `auto` | Full hierarchical swarm (Queen decides) |
| `coder` | Code team (Planner→Writer→Tester→Reviewer) |
| `researcher` | Research team (Searcher→Synthesizer→Verifier) |
| `analyst` | Analysis team (Reasoner→Critiquer→Summarizer) |
| `validator` | Validation team (Correctness+Completeness→Scorer) |
| `executor` | Execution team (Planner→Runner) |

**Response:**
```json
{
  "session_id": "...",
  "status": "complete",
  "result": "## Test Suite\n...",
  "team_used": "coder",
  "tasks_completed": 4,
  "tokens_used": 8500
}
```

---

### GET /v1/nellie/sessions

Nellie's session history overview.

---

### GET /v1/nellie/health

Swarm health from Nellie's perspective.

**Response:**
```json
{
  "swarm_status": "operational",
  "active_nanobots": 0,
  "role_distribution": {},
  "failed_queue": 0,
  "redis_memory_mb": 1.2
}
```
