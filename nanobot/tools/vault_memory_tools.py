"""
Vault Memory Tools — high-level memory tools for Nellie's knowledge vault.

Combines vector semantic search + graph queries + vault writes into
agent-friendly tools optimized for memory recall and learning.

These complement the lower-level graph_query/graph_update tools with
memory-specific semantics (recall, memorize, forget, summarize).
"""

import json
import time
import structlog

from nanobot.tools.base import BaseTool, ToolResult
from nanobot.knowledge.vault import vault, CATEGORIES, _slugify

log = structlog.get_logger()

# Will be injected at startup from gateway
_vector_store = None


def set_vector_store(vs) -> None:
    global _vector_store
    _vector_store = vs


class VaultRecallTool(BaseTool):
    """Semantic memory recall — find relevant knowledge from past interactions."""

    name = "memory_recall"
    description = (
        "Search Nellie's long-term memory for relevant knowledge. "
        "Uses hybrid semantic + keyword search across all vault notes. "
        "Returns matching entities with context, relationships, and relevance scores. "
        "Use this BEFORE answering questions — it provides accumulated knowledge "
        "from past conversations, emails, meetings, and swarm sessions."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language query to search memory (e.g., 'What do I know about Jim's Q3 roadmap?')",
            },
            "category": {
                "type": "string",
                "enum": CATEGORIES,
                "description": "Optional: filter by category (people, companies, projects, topics, etc.)",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results (default: 8)",
                "default": 8,
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str, category: str | None = None, max_results: int = 8) -> ToolResult:
        t0 = time.time()
        try:
            results = []

            # 1. Vector semantic search (if available)
            if _vector_store:
                vector_results = _vector_store.hybrid_search(
                    query, top_k=max_results,
                    type_filter=category,
                )
                for r in vector_results:
                    results.append({
                        "source": "semantic",
                        "score": r.score,
                        "title": r.title,
                        "type": r.entity_type,
                        "path": r.path,
                        "tags": r.tags,
                        "snippet": r.snippet,
                    })

            # 2. Graph keyword search (catches exact name matches the vector might miss)
            graph_results = vault.search(query, category=category, max_results=max_results)
            seen_paths = {r["path"] for r in results}
            for gr in graph_results:
                path = gr.get("path", "")
                if path not in seen_paths:
                    results.append({
                        "source": "graph",
                        "score": 0.5,  # graph results don't have scores
                        "title": gr.get("name", gr.get("title", "")),
                        "type": gr.get("category", ""),
                        "path": path,
                        "tags": gr.get("tags", []),
                        "snippet": gr.get("content", "")[:300],
                    })

            # Sort by score descending, limit
            results.sort(key=lambda x: x["score"], reverse=True)
            results = results[:max_results]

            if not results:
                return ToolResult(
                    tool_name=self.name, success=True,
                    output=f"No memories found for: '{query}'. This is a new topic — consider using memory_save to record it.",
                    duration_seconds=time.time() - t0,
                )

            output = json.dumps(results, indent=2)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output, raw=results,
                duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Memory recall failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class VaultMemorizeTool(BaseTool):
    """Save new knowledge to Nellie's long-term memory."""

    name = "memory_save"
    description = (
        "Save new information to Nellie's long-term memory (knowledge vault). "
        "Use this to record important facts, decisions, relationships, "
        "action items, or context learned during conversations. "
        "Information saved here persists across sessions and is retrievable "
        "via memory_recall. Always include [[wikilinks]] to connect related entities."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": CATEGORIES,
                "description": "Category: people, companies, projects, topics, decisions, commitments, meetings, daily",
            },
            "name": {
                "type": "string",
                "description": "Entity name (e.g., 'Jim Ross', 'Project Alpha', 'Switch to PostgreSQL')",
            },
            "content": {
                "type": "string",
                "description": "Knowledge content in Markdown. Use [[wikilinks]] for relationships.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for categorization (e.g., ['urgent', 'q3', 'investor'])",
            },
            "backlinks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Related entities to link (e.g., ['Tommy Xaypanya', 'NeuralQuantum.ai'])",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence 0.0-1.0 (default: 0.85). Use lower values for uncertain info.",
                "default": 0.85,
            },
        },
        "required": ["category", "name", "content"],
    }

    async def run(
        self,
        category: str,
        name: str,
        content: str,
        tags: list[str] | None = None,
        backlinks: list[str] | None = None,
        confidence: float = 0.85,
    ) -> ToolResult:
        t0 = time.time()
        try:
            existing = vault.read_note(category, name)
            if existing:
                vault.update_note(
                    category, name,
                    append_content=content,
                    new_backlinks=backlinks,
                    new_confidence=confidence,
                )
                action = "updated"
            else:
                vault.create_note(
                    category, name, content,
                    backlinks=backlinks,
                    confidence=confidence,
                    metadata={"tags": tags} if tags else None,
                )
                action = "created"

            # Trigger incremental vector index update
            if _vector_store:
                try:
                    note_path = vault.root / category / f"{_slugify(name)}.md"
                    if note_path.exists():
                        _vector_store.index_note(str(note_path))
                except Exception as e:
                    log.warning("memory_save_vector_index_failed", error=str(e))

            return ToolResult(
                tool_name=self.name, success=True,
                output=f"Memory {action}: {category}/{name}. "
                       f"{'Linked to: ' + ', '.join(backlinks) if backlinks else 'No links added.'}",
                duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Memory save failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class VaultContextTool(BaseTool):
    """Get today's context — daily note, recent activity, and active commitments."""

    name = "memory_context"
    description = (
        "Get Nellie's current context: today's daily note, recent vault activity, "
        "and active commitments/action items. Use this at the START of every session "
        "to ground yourself in what's happening today."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "token_budget": {
                "type": "integer",
                "description": "Max tokens of context to return (default: 2000)",
                "default": 2000,
            },
        },
    }

    async def run(self, token_budget: int = 2000) -> ToolResult:
        t0 = time.time()
        try:
            from nanobot.knowledge.graph_builder import graph_builder
            context = graph_builder.load_graph_context(token_budget=token_budget)
            return ToolResult(
                tool_name=self.name, success=True,
                output=context if context != "(empty vault)" else "No vault context yet. Start building memory with memory_save.",
                duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Context load failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


def register_vault_memory_tools(registry) -> None:
    """Register vault memory tools with a ToolRegistry."""
    registry.register(VaultRecallTool())
    registry.register(VaultMemorizeTool())
    registry.register(VaultContextTool())
    log.info("vault_memory_tools_registered", count=3)
