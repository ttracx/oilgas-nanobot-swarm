"""
Knowledge Graph Tools — allows nanobot agents to query and update the knowledge vault.

These tools are registered in the ToolRegistry so any agent in the swarm
can read/write knowledge during execution.
"""

import json
import time
import structlog

from nanobot.tools.base import BaseTool, ToolResult
from nanobot.knowledge.vault import vault, CATEGORIES

log = structlog.get_logger()


class GraphQueryTool(BaseTool):
    """Search the knowledge graph for entities, relationships, and context."""

    name = "graph_query"
    description = (
        "Search Nellie's knowledge graph for entities (people, companies, projects, topics, decisions, commitments, meetings). "
        "Returns matching notes with content, backlinks, and metadata. Use this to recall past context, "
        "find related entities, or understand relationships."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — matches note names, aliases, tags, and content",
            },
            "category": {
                "type": "string",
                "enum": CATEGORIES,
                "description": "Optional: filter by category",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return (default: 10)",
                "default": 10,
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str, category: str | None = None, max_results: int = 10) -> ToolResult:
        t0 = time.time()
        try:
            results = vault.search(query, category=category, max_results=max_results)
            output = json.dumps(results, indent=2, default=str)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output if results else "No matching notes found.",
                raw=results,
                duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Knowledge graph query failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class GraphUpdateTool(BaseTool):
    """Create or update a note in the knowledge graph."""

    name = "graph_update"
    description = (
        "Create or update a note in Nellie's knowledge graph. "
        "Use this to record new information, add relationships (backlinks), "
        "or update existing entities with new context. "
        "Always use [[wikilinks]] in backlinks to connect related entities."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "append"],
                "description": "create new note, update metadata/links, or append content to existing note",
            },
            "category": {
                "type": "string",
                "enum": CATEGORIES,
                "description": "Note category",
            },
            "name": {
                "type": "string",
                "description": "Entity name (e.g., 'Alice Smith', 'Nanobot Swarm', 'Use Redis for caching')",
            },
            "content": {
                "type": "string",
                "description": "Note content (Markdown). For 'append', this is added to the existing note.",
            },
            "backlinks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Related entities to link with [[wikilinks]] (e.g., ['Alice Smith', 'Project Alpha'])",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score 0.0-1.0 (default: 0.9)",
                "default": 0.9,
            },
        },
        "required": ["action", "category", "name"],
    }

    async def run(
        self,
        action: str,
        category: str,
        name: str,
        content: str = "",
        backlinks: list[str] | None = None,
        confidence: float = 0.9,
    ) -> ToolResult:
        t0 = time.time()
        try:
            if action == "create":
                path = vault.create_note(
                    category, name, content,
                    backlinks=backlinks, confidence=confidence,
                )
                return ToolResult(
                    tool_name=self.name, success=True,
                    output=f"Created note: {category}/{name} at {path}",
                    duration_seconds=time.time() - t0,
                )
            elif action in ("update", "append"):
                path = vault.update_note(
                    category, name,
                    append_content=content if content else None,
                    new_backlinks=backlinks,
                )
                if path:
                    return ToolResult(
                        tool_name=self.name, success=True,
                        output=f"Updated note: {category}/{name}",
                        duration_seconds=time.time() - t0,
                    )
                else:
                    path = vault.create_note(
                        category, name, content,
                        backlinks=backlinks, confidence=confidence,
                    )
                    return ToolResult(
                        tool_name=self.name, success=True,
                        output=f"Note didn't exist, created: {category}/{name} at {path}",
                        duration_seconds=time.time() - t0,
                    )
            else:
                return ToolResult(
                    tool_name=self.name, success=False,
                    output=f"Unknown action: {action}", error="invalid_action",
                    duration_seconds=time.time() - t0,
                )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Knowledge graph update failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class GraphBacklinksTool(BaseTool):
    """Find all notes that reference a specific entity (reverse backlinks)."""

    name = "graph_backlinks"
    description = (
        "Find all knowledge graph notes that link TO a given entity. "
        "This reveals relationships — which projects mention a person, "
        "which decisions relate to a topic, etc. Includes context around each link."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "entity": {
                "type": "string",
                "description": "Entity name to find reverse backlinks for",
            },
        },
        "required": ["entity"],
    }

    async def run(self, entity: str) -> ToolResult:
        t0 = time.time()
        try:
            results = vault.find_backlinks_to(entity)
            output = json.dumps(results, indent=2, default=str)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output if results else f"No notes link to '{entity}'.",
                raw=results, duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Backlinks query failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


class GraphIndexTool(BaseTool):
    """Get the full knowledge graph index — all entities and their relationships."""

    name = "graph_index"
    description = (
        "Get the complete knowledge graph index with all entities organized by category. "
        "Use this for broad context before starting a task, "
        "or to understand the full scope of Nellie's accumulated knowledge."
    )
    parameters_schema = {"type": "object", "properties": {}}

    async def run(self) -> ToolResult:
        t0 = time.time()
        try:
            index = vault.build_index()
            output = json.dumps(index, indent=2, default=str)
            return ToolResult(
                tool_name=self.name, success=True,
                output=output, raw=index, duration_seconds=time.time() - t0,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name, success=False,
                output=f"Index build failed: {e}",
                error=str(e), duration_seconds=time.time() - t0,
            )


def register_knowledge_tools(registry) -> None:
    """Register all knowledge graph tools with a ToolRegistry."""
    registry.register(GraphQueryTool())
    registry.register(GraphUpdateTool())
    registry.register(GraphBacklinksTool())
    registry.register(GraphIndexTool())
    log.info("knowledge_tools_registered", count=4)
