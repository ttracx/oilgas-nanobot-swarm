"""
Tool base class and registry.
All tools follow this interface — nanobot agents call them via ToolRouter.
"""

import abc
from dataclasses import dataclass, field
from typing import Any
import structlog

log = structlog.get_logger()


@dataclass
class ToolResult:
    """Structured result from any tool execution."""
    tool_name: str
    success: bool
    output: str
    raw: Any = None
    error: str | None = None
    duration_seconds: float = 0.0


class BaseTool(abc.ABC):
    """Abstract base — all tools implement this interface."""

    name: str = ""
    description: str = ""
    parameters_schema: dict = {}

    @abc.abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        ...

    def to_openai_function(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> "ToolRegistry":
        self._tools[tool.name] = tool
        log.info("tool_registered", name=tool.name)
        return self

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def as_openai_functions(self) -> list[dict]:
        return [t.to_openai_function() for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
