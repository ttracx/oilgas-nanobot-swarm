"""
Vault Seeder — initializes the knowledge graph with starter entities.

Run this to seed Nellie's vault with your core entities so agents
have context from day one.

Usage:
    python -m nanobot.knowledge.seed_vault
"""

from nanobot.knowledge.vault import vault


def seed_vault() -> None:
    """Seed the vault with NeuralQuantum ecosystem entities."""

    # ── People ───────────────────────────────────────────────────────────

    vault.create_note(
        "people", "Tommy Xaypanya",
        content=(
            "Chief AI & Quantum Systems Officer.\n\n"
            "## Key Context\n"
            "- Leads technical strategy across all organizations\n"
            "- Primary architect of VibeCaaS, NeuralQuantum, and agent systems\n"
            "- Manages Nellie (OpenClaw agent) and the Nanobot Swarm\n\n"
            "## History\n"
        ),
        metadata={"role": "Chief AI & Quantum Systems Officer"},
        backlinks=["NeuralQuantum.ai", "VibeCaaS", "Tunaas.ai", "NeuroEquality", "SnuggleCrafters"],
        aliases=["Tommy", "TX"],
        confidence=1.0,
    )

    vault.create_note(
        "people", "Jim Ross",
        content=(
            "CEO of NeuralQuantum.ai.\n\n"
            "## Key Context\n"
            "- Chief Executive Officer overseeing business operations\n"
            "- Works closely with Tommy Xaypanya on strategic direction\n\n"
            "## History\n"
        ),
        metadata={"role": "CEO"},
        backlinks=["NeuralQuantum.ai", "Tommy Xaypanya", "Craig Ross"],
        confidence=1.0,
    )

    vault.create_note(
        "people", "Craig Ross",
        content=(
            "CPO of NeuralQuantum.ai.\n\n"
            "## Key Context\n"
            "- Chief Product Officer driving product strategy\n"
            "- Leads product development across the NeuralQuantum portfolio\n\n"
            "## History\n"
        ),
        metadata={"role": "CPO"},
        backlinks=["NeuralQuantum.ai", "Tommy Xaypanya", "Jim Ross"],
        confidence=1.0,
    )

    # ── Companies ────────────────────────────────────────────────────────

    vault.create_note(
        "companies", "NeuralQuantum.ai",
        content=(
            "Quantum-inspired AI algorithms and ML research company.\n\n"
            "## Key Context\n"
            "- Parent organization for quantum computing and AI research\n"
            "- Develops proprietary quantum-inspired algorithms\n"
            "- Operates the Nanobot Swarm inference system\n\n"
            "## History\n"
        ),
        backlinks=["Tommy Xaypanya", "VibeCaaS", "Tunaas.ai"],
        confidence=1.0,
    )

    vault.create_note(
        "companies", "VibeCaaS",
        content=(
            "Vibe Coding as a Service — unified AI-powered creativity platform.\n\n"
            "## Key Context\n"
            "- Consolidates PatentPalette.ai, VibeTales.ai, SnuggleCrafters, YouCanBeABCs.org\n"
            "- Vibe coding IDE with end-to-end development\n"
            "- Next.js 14 + TypeScript + Tailwind + shadcn/ui stack\n\n"
            "## History\n"
        ),
        backlinks=["Tommy Xaypanya", "NeuralQuantum.ai", "SnuggleCrafters"],
        confidence=1.0,
    )

    vault.create_note(
        "companies", "Tunaas.ai",
        content=(
            "AI platform infrastructure and tooling.\n\n"
            "## Key Context\n"
            "- Provides AI infrastructure for the NeuralQuantum ecosystem\n\n"
            "## History\n"
        ),
        backlinks=["Tommy Xaypanya", "NeuralQuantum.ai"],
        confidence=1.0,
    )

    vault.create_note(
        "companies", "NeuroEquality",
        content=(
            "Neurodiverse technologies development (LLC).\n\n"
            "## Key Context\n"
            "- Focuses on technologies for neurodivergent users\n\n"
            "## History\n"
        ),
        backlinks=["Tommy Xaypanya"],
        confidence=1.0,
    )

    vault.create_note(
        "companies", "SnuggleCrafters",
        content=(
            "AI storytelling platform.\n\n"
            "## Key Context\n"
            "- Part of VibeCaaS consolidation\n"
            "- AI-powered character generation and storytelling\n\n"
            "## History\n"
        ),
        backlinks=["Tommy Xaypanya", "VibeCaaS"],
        confidence=1.0,
    )

    # ── Projects ─────────────────────────────────────────────────────────

    vault.create_note(
        "projects", "Nanobot Swarm",
        content=(
            "Hierarchical multi-agent inference system.\n\n"
            "## Key Context\n"
            "- 3-tier hierarchy: Queen (L0) → Domain Leads (L1) → Sub-agents (L2)\n"
            "- 22 total agents across 6 domains (Coder, Researcher, Analyst, Validator, Executor, Architect)\n"
            "- Redis-backed state, vLLM/Ollama LLM backend\n"
            "- OpenAI-compatible API gateway on port 8100\n"
            "- Integrated with Nellie via OpenClaw connector\n\n"
            "## History\n"
        ),
        backlinks=["Tommy Xaypanya", "NeuralQuantum.ai", "Nellie"],
        confidence=1.0,
    )

    vault.create_note(
        "projects", "Nellie",
        content=(
            "OpenClaw agent — Nellie is the primary AI assistant.\n\n"
            "## Key Context\n"
            "- Personal AI agent with persistent memory\n"
            "- Manages the Nanobot Swarm for task delegation\n"
            "- Knowledge graph for long-term memory\n"
            "- Background agent swarms for automated workflows\n"
            "- Workspace at ~/.nellienano/\n\n"
            "## History\n"
        ),
        backlinks=["Tommy Xaypanya", "Nanobot Swarm", "NeuralQuantum.ai"],
        confidence=1.0,
    )

    vault.create_note(
        "projects", "VibeCaaS Platform",
        content=(
            "The VibeCaaS web platform — consolidation of all sub-apps.\n\n"
            "## Key Context\n"
            "- Next.js 14 App Router + TypeScript strict mode\n"
            "- PostgreSQL (Neon), MongoDB (Atlas), Redis (Cloud)\n"
            "- Vercel hosting, GitHub Actions CI/CD\n"
            "- Combines PatentPalette.ai, VibeTales.ai, SnuggleCrafters, YouCanBeABCs.org\n\n"
            "## History\n"
        ),
        backlinks=["VibeCaaS", "Tommy Xaypanya"],
        confidence=1.0,
    )

    # ── Topics ───────────────────────────────────────────────────────────

    for topic_name, desc in [
        ("Quantum Computing", "Quantum-inspired algorithms and quantum circuit design."),
        ("Knowledge Graphs", "Markdown-based knowledge graphs with backlinks for persistent agent memory."),
        ("Agent Swarms", "Multi-agent orchestration with hierarchical task decomposition."),
        ("MCP Servers", "Model Context Protocol for tool integration across agents."),
        ("Local LLM Inference", "Running LLMs locally via vLLM and Ollama."),
    ]:
        vault.create_note(
            "topics", topic_name,
            content=f"{desc}\n\n## Notes\n\n## History\n",
            backlinks=["NeuralQuantum.ai"],
            confidence=1.0,
        )

    # ── Create today's daily note ────────────────────────────────────────
    vault.create_daily_note()

    stats = vault.get_stats()
    print(f"Vault seeded at {stats['vault_path']}")
    print(f"Total notes: {stats['total_notes']}")
    for cat, count in stats["categories"].items():
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    seed_vault()
