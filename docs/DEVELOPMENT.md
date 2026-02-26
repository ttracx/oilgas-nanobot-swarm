# Development Guide

---

## Prerequisites

- Python 3.11+
- Redis 7+ (via Docker: `docker run -d -p 6379:6379 redis:7.4-alpine`)
- Git

---

## Setup

```bash
git clone https://github.com/ttracx/oilgas-nanobot-swarm.git
cd oilgas-nanobot-swarm

# Install in editable mode with dev deps
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — set OLLAMA_API_KEY at minimum

# Start
python -m uvicorn nanobot.api.gateway:app --reload --port 8100
```

---

## Project Structure

```
oilgas-nanobot-swarm/
│
├── api/                        # Vercel serverless entry point
│   ├── index.py                # FastAPI app (Ollama Cloud + NVIDIA NIM)
│   └── requirements.txt        # Slim deps for Vercel function
│
├── nanobot/                    # Main Python package
│   ├── core/                   # Agent hierarchy
│   │   ├── agent.py            # Base NanobotAgent + AgentRole enums
│   │   ├── agent_v2.py         # Tool-use agent with agentic loop
│   │   ├── agent_v3.py         # Redis-backed state persistence
│   │   ├── agent_claude.py     # Anthropic Claude agent
│   │   ├── claude_runner.py    # ClaudeTeamRunner (tool dispatch)
│   │   ├── hierarchical_swarm.py  # 3-tier Queen→L1→L2 orchestrator
│   │   ├── orchestrator.py     # Flat swarm orchestrator
│   │   ├── l1_agent.py         # L1 domain lead with sub-swarm
│   │   ├── sub_swarm.py        # Per-L1 mini-swarm pipeline
│   │   ├── sub_prompts.py      # 15 L2 system prompts
│   │   └── roles.py            # L0/L1/L2 role enums
│   │
│   ├── tools/                  # Agentic tool system
│   │   ├── base.py             # BaseTool ABC + ToolRegistry
│   │   ├── router.py           # Tool-use loop engine (agentic loop)
│   │   ├── oilgas_tools.py     # 7 O&G engineering calculators  ← O&G
│   │   ├── web_search.py       # DuckDuckGo search
│   │   ├── code_runner.py      # Sandboxed Python execution
│   │   ├── file_io.py          # Workspace file I/O
│   │   ├── http_fetch.py       # URL content fetcher
│   │   ├── knowledge_tools.py  # Knowledge graph query/update
│   │   ├── vault_memory_tools.py  # Vault-backed memory
│   │   └── msgraph_tools.py    # Microsoft 365 tools
│   │
│   ├── teams/                  # Agent team configurations
│   │   └── oilgas_teams.py     # 9 O&G pre-built teams          ← O&G
│   │
│   ├── scheduler/              # Background job scheduler
│   │   ├── agent_teams.py      # AgentTeam dataclass + registry
│   │   └── scheduler.py        # Cron/interval job executor
│   │
│   ├── knowledge/              # Knowledge vault
│   │   ├── vault.py            # Markdown knowledge graph
│   │   ├── vector_store.py     # Embeddings + similarity search
│   │   └── graph_builder.py    # Async background indexer
│   │
│   ├── state/                  # Redis persistence
│   │   ├── connection.py       # Async pool singleton
│   │   ├── swarm_state.py      # Session/agent registry
│   │   └── task_journal.py     # Audit trail
│   │
│   ├── integrations/           # External services
│   │   ├── openclaw_connector.py  # OpenAI-compat API for Nellie
│   │   ├── microsoft_graph.py     # MS 365 integration
│   │   └── nellie_memory_bridge.py
│   │
│   ├── api/                    # Full-stack FastAPI gateway
│   │   └── gateway.py          # Gateway with all subsystems
│   │
│   └── static/
│       └── index.html          # NeuralQuantum-branded dashboard
│
├── docs/                       # This documentation
├── scripts/                    # Setup scripts
├── tests/                      # Test suite
├── .devcontainer/              # GitHub Codespaces
├── docker-compose.yml          # Local dev stack
├── Dockerfile                  # Production container
├── render.yaml                 # Render deployment
├── railway.toml                # Railway deployment
└── vercel.json                 # Vercel deployment (functions config)
```

---

## Adding a New Engineering Tool

Tools live in `nanobot/tools/`. Implement the `BaseTool` ABC:

```python
# nanobot/tools/my_new_tool.py
import time
from nanobot.tools.base import BaseTool, ToolResult


class MyEngineeringTool(BaseTool):
    name = "my_calc"
    description = (
        "Calculate [something]. "
        "Used for [when to use it]. "
        "Supports: [calc_type_1], [calc_type_2]."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "calc_type": {
                "type": "string",
                "enum": ["type_a", "type_b"],
                "description": "Type of calculation",
            },
            "value_a": {
                "type": "number",
                "description": "Input A with units (e.g., ppg)",
            },
        },
        "required": ["calc_type", "value_a"],
    }

    async def run(self, calc_type: str, value_a: float, **kwargs) -> ToolResult:
        start = time.time()
        try:
            if calc_type == "type_a":
                result = value_a * 0.052  # example calculation
                output = f"Result: {result:.4f} psi/ft\nFormula: value × 0.052"
            else:
                output = "Unknown calc_type"

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw={"result": result},
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Calculation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )
```

Register it in `nanobot/tools/oilgas_tools.py`:

```python
def get_oilgas_tools() -> list[BaseTool]:
    return [
        ReservoirPressureCalcTool(),
        DrillingEngineeringTool(),
        # ...
        MyEngineeringTool(),  # Add here
    ]
```

---

## Adding a New Agent Team

Teams are registered in `nanobot/teams/oilgas_teams.py`:

```python
from nanobot.scheduler.agent_teams import AgentTeam, register_team

register_team(AgentTeam(
    name="my-team",                         # kebab-case, unique
    description="One-line description for the dashboard",
    mode="hierarchical",                    # "hierarchical" or "flat"
    backend="auto",                         # "auto", "claude", or "vllm"
    system_prompt="""You are the [Role] Team.

Your mandate:
[Describe the team's purpose]

Workflow:
1. [Step one — use specific tools]
   - Use [tool_name] to [action]
2. [Step two]
3. [Step three]

Output Format:
## [Section Title]
### [Subsection]
[content]
""",
    inject_knowledge=True,                  # Pull knowledge graph context
    inject_history=True,                    # Include recent session history
    update_knowledge_after=True,            # Persist outputs to vault
    max_tokens=4096,
    temperature=0.1,                        # Low for engineering (deterministic)
))
```

Teams are auto-loaded when `ENABLE_OILGAS_TEAMS=true`.

---

## AI Backend Architecture

The Vercel deployment (`api/index.py`) uses a simple two-backend pattern:

```
Request
  │
  ├──► Ollama Cloud (primary)
  │      base_url: https://ollama.com/v1
  │      model: ministral-3:8b
  │      timeout: 50s
  │
  └──► NVIDIA NIM (fallback, if Ollama fails)
         base_url: https://integrate.api.nvidia.com/v1
         model: meta/llama-3.3-70b-instruct
         timeout: 50s
```

The full-stack gateway (`nanobot/api/gateway.py`) uses:
- Anthropic Claude (cloud, high quality)
- vLLM (local GPU inference)

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=nanobot --cov-report=html

# Specific file
pytest tests/test_oilgas_tools.py -v

# Import validation only
pytest tests/test_imports.py -v
```

---

## Code Standards

### Python Style
- Type hints on all function signatures
- `async def` for all I/O operations
- No `any` types — use specific types
- `structlog` for structured logging (not `print`)

### Engineering Tools
- Always include the governing equation in the output
- Reference the source (author, year)
- Include disclaimer at the end of each result
- Handle edge cases (division by zero, negative values)

### Agent Teams
- System prompts should be explicit about workflow steps
- Reference specific tool names so agents know what's available
- Specify output format for consistent parsing

---

## Contributing

1. Fork → Clone → Branch
2. Implement with tests
3. `pytest tests/ -v` — all green
4. PR with description of engineering use case

```bash
git checkout -b feat/my-feature
# implement
pytest tests/ -v
git push origin feat/my-feature
# open PR at https://github.com/ttracx/oilgas-nanobot-swarm
```

---

## Pro Edition

> **⭐ Pro Edition** — full hierarchical swarm, Redis memory, knowledge vault, scheduler, MS 365 integration.
>
> Contact: [info@neuralquantum.ai](mailto:info@neuralquantum.ai)
