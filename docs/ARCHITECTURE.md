# Architecture

## System Overview

The Nanobot Swarm is a 3-tier hierarchical multi-agent system that decomposes complex goals into specialized subtasks, executes them in parallel where possible, and synthesizes results into comprehensive answers.

## Tier Structure

### L0 — Queen Orchestrator

The Queen receives a goal and produces a structured execution plan as JSON. She determines which L1 domain leads to activate, what instructions to give each, and how to synthesize their outputs.

**Responsibilities:**
- Parse and understand the goal
- Decompose into L1-level tasks
- Determine dependencies between tasks
- Define synthesis strategy
- Review and compile final answer

**Temperature:** 0.0 (deterministic planning)

### L1 — Domain Leads

Each L1 agent is a domain specialist that commands its own sub-swarm of L2 agents. The L1 performs three phases:

1. **Contextualize** — Analyze the task, add domain-specific constraints and quality criteria
2. **Delegate** — Run the sub-swarm pipeline (L2 agents execute in stages)
3. **Review** — Inspect sub-swarm output, add expertise layer, produce final output

| L1 Role | Sub-Swarm Pipeline | Description |
|---------|-------------------|-------------|
| Coder | Planner → Writer → [Tester + Reviewer] | Full implementation lifecycle |
| Researcher | Searcher → [Synthesizer + Verifier] | Search, synthesize, fact-check |
| Analyst | Reasoner → Critiquer → Summarizer | Deep analysis with self-critique |
| Validator | [Correctness + Completeness] → Scorer | Multi-dimension quality checks |
| Executor | Planner → Runner | Action sequencing and execution |
| Architect | (solo, no sub-swarm) | System design specialist |

### L2 — Sub-Agents

Highly specialized agents with narrow, deep focus. Each has a tailored system prompt that constrains its behavior to a single competency. L2 agents:

- Execute a single stage of the L1 pipeline
- Receive context from prior stages
- Use tools (search, code, files, HTTP) when needed
- Return structured output for the next stage

## Execution Flow

```
Goal arrives
    │
    ▼
Queen.plan(goal) → JSON plan with l1_tasks[]
    │
    ▼
Group tasks by dependency level
    │
    ▼
For each level (parallel within level):
    │
    ├── L1Agent.execute(task)
    │       │
    │       ├── Phase 1: L1 contextualizes task
    │       ├── Phase 2: SubSwarm executes pipeline
    │       │       │
    │       │       ├── Stage 1: [L2 agents] (parallel within stage)
    │       │       ├── Stage 2: [L2 agents] (depends on stage 1)
    │       │       └── Stage N: ...
    │       │
    │       └── Phase 3: L1 reviews sub-swarm output
    │
    ▼
Queen.synthesize(all L1 outputs) → final answer
```

## Tool System

Every agent (L1 and L2) has access to tools through the agentic loop engine:

```
Agent.execute(task)
    │
    ▼
ToolRouter.run_with_tools(messages)
    │
    ├── LLM generates response
    │   ├── If text → done, return
    │   └── If tool_call → dispatch tool
    │           │
    │           ▼
    │       Tool.run(**args) → ToolResult
    │           │
    │           ▼
    │       Inject result into messages
    │           │
    │           └── Loop back to LLM
    │
    ▼ (max 10 iterations)
    Return final text + full message trace
```

### Available Tools

| Tool | Description | Used By |
|------|-------------|---------|
| `web_search` | DuckDuckGo instant answers | Researcher, Fact Verifier |
| `http_fetch` | Fetch URLs (APIs, docs, pages) | Researcher, Web Searcher |
| `run_python` | Sandboxed Python execution (30s timeout) | Coder, Tester, Validator |
| `file_io` | Read/write files in workspace | Executor, Coder |

## State Management (Redis)

### Per-Agent Memory

Each agent has 3 memory tiers stored in Redis:

- **Short-term** (4h TTL): Sliding window of last 50 conversation turns
- **Long-term** (30d TTL): Extracted facts and domain knowledge
- **Episodic** (7d TTL): Summaries of completed task sessions

Memory context is injected into the system prompt before each execution, giving agents awareness of their prior work.

### Task Journal

Append-only audit trail for every task:
- Start time, agent ID, role, content preview
- Completion status, full output, token count, duration
- Tool calls made during execution
- Failed tasks queued for retry

### Session Lifecycle

```
create_session(goal) → session_id
    │
    ├── update_session(task_count=N)
    │
    ├── [tasks execute, agents register/deregister]
    │
    ├── update_session(completed_tasks=M)
    │
    └── complete_session(final_answer, success)
```

Sessions, agents, and health data are all queryable via the API.

## Concurrency Model

```
Global Semaphore (12 slots)
    │
    ├── L1 Semaphore (3 concurrent L1 agents)
    │       │
    │       └── Sub-Semaphore (4 concurrent L2 per L1)
    │
    └── vLLM handles batching (32 concurrent sequences)
```

This ensures the RTX 4060 Ti's 16GB VRAM is not overwhelmed. The model serves all agents through a single vLLM instance with batched inference.

## Data Flow

```
                    Nellie (OpenClaw)
                         │
                    ┌────▼─────┐
                    │ Gateway  │ ← FastAPI + OpenAI-compat
                    │  :8100   │
                    └────┬─────┘
                         │
              ┌──────────▼──────────┐
              │   HierarchicalSwarm  │
              └──────────┬──────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ┌───────────┐   ┌───────────┐   ┌───────────┐
   │ L1 Agent  │   │ L1 Agent  │   │ L1 Agent  │
   │ (Coder)   │   │ (Rsrchr)  │   │ (Analyst) │
   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
         │               │               │
    ┌────▼────┐     ┌────▼────┐     ┌────▼────┐
    │SubSwarm │     │SubSwarm │     │SubSwarm │
    │ 4 L2s   │     │ 3 L2s   │     │ 3 L2s   │
    └────┬────┘     └────┬────┘     └────┬────┘
         │               │               │
         └───────────────┼───────────────┘
                         │
              ┌──────────▼──────────┐
              │   vLLM Server :8000  │ ← OpenAI-compatible API
              │   GLM-4.7-Flash MoE  │
              │   RTX 4060 Ti 16GB   │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │     Redis :6379      │ ← Memory, Journal, State
              └─────────────────────┘
```

## Key Design Decisions

1. **Single vLLM instance**: All agents share one model server. vLLM's continuous batching handles concurrent requests efficiently. This maximizes GPU utilization.

2. **Hierarchical over flat**: A flat swarm of 10+ agents produces noisy, poorly-coordinated output. The 3-tier hierarchy ensures each agent has clear scope and produces focused results.

3. **L1 contextualize-delegate-review**: L1 agents don't just pass tasks through. They add domain expertise before and after the sub-swarm runs, catching issues the narrow L2 agents miss.

4. **Redis for state, not SQLite**: Agent memory needs sub-millisecond reads and writes. Redis sorted sets and lists are ideal for sliding window conversations and fact stores.

5. **OpenAI-compatible API**: Nellie and any OpenAI client can use the swarm as if it were a model. No custom SDK needed.
