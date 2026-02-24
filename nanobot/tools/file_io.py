"""
File read/write tool for nanobots.
Sandboxed to a configurable workspace directory.
"""

import time
import os
from pathlib import Path
from nanobot.tools.base import BaseTool, ToolResult

DEFAULT_WORKSPACE = Path.home() / "nanobot_workspace"


class FileIOTool(BaseTool):
    name = "file_io"
    description = (
        "Read, write, append, or list files in the agent workspace. "
        "Use to persist results, read config, or share data between agent tasks."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "append", "list", "exists"],
                "description": "Operation to perform",
            },
            "path": {
                "type": "string",
                "description": "Relative file path within workspace",
            },
            "content": {
                "type": "string",
                "description": "Content to write (for write/append operations)",
            },
        },
        "required": ["operation", "path"],
    }

    def __init__(self, workspace: Path = DEFAULT_WORKSPACE):
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative: str) -> Path:
        resolved = (self.workspace / relative).resolve()
        if not str(resolved).startswith(str(self.workspace.resolve())):
            raise PermissionError(f"Path escape attempt blocked: {relative}")
        return resolved

    async def run(
        self,
        operation: str,
        path: str,
        content: str | None = None,
        **kwargs,
    ) -> ToolResult:
        start = time.time()
        try:
            safe = self._safe_path(path)

            if operation == "read":
                if not safe.exists():
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        output=f"File not found: {path}",
                        error="not_found",
                    )
                text = safe.read_text(encoding="utf-8")
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output=f"Content of {path}:\n\n{text}",
                    raw=text,
                    duration_seconds=time.time() - start,
                )

            elif operation == "write":
                safe.parent.mkdir(parents=True, exist_ok=True)
                safe.write_text(content or "", encoding="utf-8")
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output=f"Written {len(content or '')} chars to {path}",
                    duration_seconds=time.time() - start,
                )

            elif operation == "append":
                safe.parent.mkdir(parents=True, exist_ok=True)
                with open(safe, "a", encoding="utf-8") as f:
                    f.write(content or "")
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output=f"Appended {len(content or '')} chars to {path}",
                    duration_seconds=time.time() - start,
                )

            elif operation == "list":
                target = safe if safe.is_dir() else safe.parent
                entries = [
                    f"{'[DIR] ' if e.is_dir() else '[FILE]'} {e.name}"
                    for e in sorted(target.iterdir())
                ]
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output=f"Contents of {path}:\n" + "\n".join(entries),
                    raw=entries,
                    duration_seconds=time.time() - start,
                )

            elif operation == "exists":
                exists = safe.exists()
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output=f"{path}: {'exists' if exists else 'does not exist'}",
                    raw=exists,
                    duration_seconds=time.time() - start,
                )

            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    output=f"Unknown operation: {operation}",
                    error="unknown_operation",
                )

        except PermissionError as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Permission denied: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"File operation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )
