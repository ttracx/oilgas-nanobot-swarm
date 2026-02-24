# Agent Role Reference

## Tier Overview

| Tier | Count | Purpose |
|------|-------|---------|
| L0 (Queen) | 1 | Strategic decomposition and synthesis |
| L1 (Domain Leads) | 6 | Domain expertise, sub-swarm command |
| L2 (Sub-Agents) | 15 | Narrow specialization, pipeline stages |
| **Total** | **22** | |

---

## L0 — Queen Orchestrator

**Role:** `orchestrator`

The Queen receives raw goals and produces structured execution plans. She decides which L1 teams to activate, sets task dependencies, and synthesizes all results into a final answer.

**Behavior:**
- Temperature: 0.0 (deterministic)
- Output: JSON plan with `l1_tasks[]` array
- Runs twice per session: once for planning, once for synthesis

---

## L1 — Domain Leads

### Coder Lead

**Role:** `coder`

Commands the code sub-swarm. Adds architectural context before delegation, reviews code quality after.

**Sub-swarm pipeline:**
```
Stage 1: Code Planner (sequential)
Stage 2: Code Writer (sequential, depends on planner)
Stage 3: Code Tester + Code Reviewer (parallel)
```

**Best for:** Implementation tasks, code generation, refactoring, debugging.

---

### Researcher Lead

**Role:** `researcher`

Commands the research sub-swarm. Defines research scope, evaluates finding quality.

**Sub-swarm pipeline:**
```
Stage 1: Web Searcher (sequential)
Stage 2: Synthesizer + Fact Verifier (parallel)
```

**Best for:** Information gathering, documentation research, competitive analysis.

---

### Analyst Lead

**Role:** `analyst`

Commands the analysis sub-swarm. Frames analysis questions, evaluates reasoning quality.

**Sub-swarm pipeline:**
```
Stage 1: Reasoner (sequential)
Stage 2: Critiquer (sequential, critiques the reasoning)
Stage 3: Summarizer (sequential, condenses all analysis)
```

**Best for:** Decision analysis, architecture evaluation, trade-off analysis, deep reasoning.

---

### Validator Lead

**Role:** `validator`

Commands the validation sub-swarm. Sets validation criteria, interprets scores.

**Sub-swarm pipeline:**
```
Stage 1: Correctness + Completeness (parallel)
Stage 2: Scorer (sequential, scores based on both checks)
```

**Best for:** Quality assurance, output verification, review gates.

---

### Executor Lead

**Role:** `executor`

Commands the execution sub-swarm. Defines success criteria, monitors execution.

**Sub-swarm pipeline:**
```
Stage 1: Action Planner (sequential)
Stage 2: Action Runner (sequential, executes the plan)
```

**Best for:** Multi-step action sequences, file operations, system tasks.

---

### Architect

**Role:** `architect`

Solo agent (no sub-swarm). System design specialist.

**Best for:** Architecture decisions, technology selection, integration patterns, system diagrams.

---

## L2 — Sub-Agents

### Coder Sub-Swarm

| Role | Focus | Tools Used |
|------|-------|-----------|
| `code_planner` | Data structures, signatures, test cases, edge cases | None (planning only) |
| `code_writer` | Complete implementation from plan | `file_io` |
| `code_tester` | pytest test cases + execution | `run_python` |
| `code_reviewer` | Quality, security, performance review | None (review only) |

### Researcher Sub-Swarm

| Role | Focus | Tools Used |
|------|-------|-----------|
| `web_searcher` | Targeted multi-query web search | `web_search`, `http_fetch` |
| `synthesizer` | Structure raw findings into knowledge | None (synthesis only) |
| `fact_verifier` | Cross-reference claims against sources | `web_search` |

### Analyst Sub-Swarm

| Role | Focus | Tools Used |
|------|-------|-----------|
| `reasoner` | Step-by-step logical analysis | None (reasoning only) |
| `critiquer` | Find flaws in arguments | None (critique only) |
| `summarizer` | Compress analysis to essentials | None (summarization only) |

### Validator Sub-Swarm

| Role | Focus | Tools Used |
|------|-------|-----------|
| `correctness` | Factual and logical accuracy | `web_search`, `run_python` |
| `completeness` | Coverage of all task requirements | None (review only) |
| `scorer` | Multi-dimensional quality scoring | None (scoring only) |

### Executor Sub-Swarm

| Role | Focus | Tools Used |
|------|-------|-----------|
| `action_planner` | Convert goal to atomic action sequence | None (planning only) |
| `action_runner` | Execute actions with tools | `run_python`, `file_io`, `http_fetch` |

---

## Agent Lifecycle

```
1. Agent created by orchestrator/L1
2. agent.initialize() → registers with Redis swarm state
3. agent.execute(task) → runs agentic loop with tool use
   - Memory context injected from Redis
   - Task journaled to Redis
   - Conversation persisted to Redis
4. agent.shutdown() → deregisters from swarm state
```

## Memory Structure

Each agent maintains:

- **Conversation buffer** — Last 50 turns (4h TTL)
- **Fact store** — Key-value domain knowledge (30d TTL)
- **Episode log** — Last 100 completed task summaries (7d TTL)

Memory context is prepended to the system prompt:
```
=== AGENT MEMORY ===
RECENT TASK HISTORY:
- [1740000000] Goal: Build auth module -> OK Implemented JWT auth...

KNOWN FACTS:
- preferred_db: PostgreSQL
- api_style: RESTful with OpenAPI
=== END MEMORY ===

[Original system prompt follows]
```
