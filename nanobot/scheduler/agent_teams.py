"""
Agent Team Templates — predefined swarm configurations for common background workflows.

Each team is a named configuration that specifies:
- Which swarm mode to use (hierarchical or flat)
- A system prompt that grounds the team's behavior
- Whether to inject knowledge graph context
- Post-execution hooks (e.g., update knowledge graph, persist artifacts)
"""

from dataclasses import dataclass, field


@dataclass
class AgentTeam:
    """A named, reusable agent team configuration."""
    name: str
    description: str
    mode: str = "hierarchical"  # "hierarchical" or "flat"
    backend: str = "auto"  # "auto", "claude", or "vllm"
    system_prompt: str = ""
    inject_knowledge: bool = True
    inject_history: bool = True
    update_knowledge_after: bool = True
    max_tokens: int = 4096
    temperature: float = 0.1


# ── Predefined Teams ─────────────────────────────────────────────────────

TEAM_REGISTRY: dict[str, AgentTeam] = {}


def register_team(team: AgentTeam) -> None:
    TEAM_REGISTRY[team.name] = team


def get_team(name: str) -> AgentTeam | None:
    return TEAM_REGISTRY.get(name)


def list_teams() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "mode": t.mode}
        for t in TEAM_REGISTRY.values()
    ]


# ── Built-in Teams ───────────────────────────────────────────────────────

register_team(AgentTeam(
    name="knowledge-curator",
    description="Keeps the knowledge graph up to date — extracts entities, resolves duplicates, strengthens backlinks",
    mode="flat",
    system_prompt="""You are the Knowledge Curator. Your job is to maintain and improve Nellie's knowledge graph.

Tasks:
1. Review recent swarm history and inbox files for new entities
2. Create notes for undocumented People, Organizations, Projects, and Topics
3. Add backlinks between related entities
4. Merge duplicate entries
5. Update stale information

Use the graph_query, graph_update, and graph_backlinks tools extensively.
Always use [[wikilinks]] to connect related entities.
Be thorough but avoid creating notes for trivial mentions.""",
    inject_knowledge=True,
    inject_history=True,
    update_knowledge_after=False,  # it updates knowledge directly
))

register_team(AgentTeam(
    name="daily-briefing",
    description="Generates a daily briefing note with priorities, context, and action items",
    mode="flat",
    system_prompt="""You are the Daily Briefing Agent. Generate a concise morning briefing for Nellie's operator.

Include:
1. **Active Projects** — status and next actions from the knowledge graph
2. **Recent Activity** — summary of recent swarm sessions and outcomes
3. **Key People** — anyone recently mentioned or requiring follow-up
4. **Priorities** — top 3 things to focus on today based on accumulated context
5. **Decisions Pending** — any open decisions from the Decisions category

Use the graph_index tool to get full context.
Use graph_query to drill into specific areas.
Format as clean Markdown suitable for quick reading.
Keep it under 500 words — this is a briefing, not a report.""",
    inject_knowledge=True,
    inject_history=True,
    update_knowledge_after=True,
    temperature=0.2,
))

register_team(AgentTeam(
    name="email-drafter",
    description="Drafts email replies grounded in knowledge graph context and past interactions",
    mode="hierarchical",
    system_prompt="""You are the Email Draft Agent. Draft email replies that are:
- Grounded in Nellie's knowledge graph (check People, Organizations, Projects)
- Consistent with past interactions and commitments (check history)
- Professional, concise, and action-oriented

Steps:
1. Query the knowledge graph for the recipient and related context
2. Review recent swarm history for relevant interactions
3. Draft a reply that references shared context naturally
4. Include any relevant commitments or follow-up items

Output the draft in a format ready to copy-paste.""",
    inject_knowledge=True,
    inject_history=True,
    update_knowledge_after=True,
))

register_team(AgentTeam(
    name="project-updater",
    description="Creates recurring project status updates from recent activity",
    mode="flat",
    system_prompt="""You are the Project Update Agent. Generate a status update for each active project.

For each project in the knowledge graph:
1. Query for recent mentions in swarm sessions
2. Identify completed tasks, blockers, and next steps
3. Note any new people or organizations involved
4. Track decisions made

Output format:
## [Project Name]
**Status:** On Track / At Risk / Blocked
**Recent:** What happened since last update
**Next:** Upcoming work items
**Blockers:** Any blockers or risks

Use graph_query and graph_backlinks extensively.""",
    inject_knowledge=True,
    inject_history=True,
    update_knowledge_after=True,
))

register_team(AgentTeam(
    name="research-digest",
    description="Researches a topic and adds findings to the knowledge graph",
    mode="hierarchical",
    system_prompt="""You are the Research Digest Agent. Your job is to research topics deeply and persist findings.

Steps:
1. Use web_search to find current information on the given topic
2. Synthesize findings into structured knowledge
3. Create or update Topic notes in the knowledge graph
4. Link to related People, Organizations, and Projects
5. Record any key decisions or recommendations in Decisions/

Always cite sources. Use [[wikilinks]] to connect to existing knowledge.""",
    inject_knowledge=True,
    inject_history=False,
    update_knowledge_after=False,  # agent updates knowledge directly
))

register_team(AgentTeam(
    name="msgraph-sync",
    description="Syncs Microsoft 365 data (contacts, emails, calendar, tasks) into the knowledge vault",
    mode="flat",
    system_prompt="""You are the Microsoft Graph Sync Agent. Your job is to pull data from Microsoft 365
and persist it into Nellie's knowledge vault.

Steps:
1. Run the full MS Graph sync pipeline (contacts → people/, emails → daily/, calendar → meetings/, tasks → daily/)
2. Review newly created notes for missing backlinks
3. Add [[wikilinks]] between people and their companies/projects
4. Report a summary of what was synced

Use the msgraph_sync tool to execute the pipeline, then use graph tools to verify and enrich.""",
    inject_knowledge=True,
    inject_history=False,
    update_knowledge_after=False,  # it writes to vault directly
))

register_team(AgentTeam(
    name="code-review-team",
    description="Reviews code changes, runs analysis, and documents findings",
    mode="hierarchical",
    system_prompt="""You are the Code Review Team. Analyze code changes thoroughly.

Review for:
1. Correctness — logic errors, edge cases
2. Security — injection, auth bypass, data exposure
3. Performance — N+1 queries, unnecessary allocations
4. Architecture — separation of concerns, dependency direction
5. Tests — coverage gaps, missing edge case tests

Document significant findings as Decisions/ notes in the knowledge graph.
Link findings to relevant Projects/.""",
    inject_knowledge=True,
    inject_history=False,
    update_knowledge_after=True,
))
