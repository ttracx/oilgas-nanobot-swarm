"""
Sandboxed Python code execution tool.
Runs agent-generated code in isolated subprocess with timeout + output capture.
Uses asyncio.create_subprocess_exec for safe execution (no shell injection).
"""

import asyncio
import time
import textwrap
import tempfile
import os
from nanobot.tools.base import BaseTool, ToolResult

CODE_TIMEOUT_SECONDS = 30

BLOCKED_PATTERNS = {
    "subprocess", "os.system", "shutil.rmtree",
    "socket", "__import__",
    "open('/etc", "open('/proc", "open('/sys",
}


def _is_safe(code: str) -> tuple[bool, str]:
    code_lower = code.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in code_lower:
            return False, f"Blocked pattern detected: {pattern}"
    return True, ""


class CodeRunnerTool(BaseTool):
    name = "run_python"
    description = (
        "Execute Python code and return stdout/stderr output. "
        "Use for calculations, data processing, testing logic, or validating algorithms. "
        "Code runs in an isolated subprocess with a 30-second timeout."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute",
            },
            "description": {
                "type": "string",
                "description": "Brief description of what this code does",
            },
        },
        "required": ["code"],
    }

    async def run(self, code: str, description: str = "", **kwargs) -> ToolResult:
        start = time.time()

        safe, reason = _is_safe(code)
        if not safe:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"BLOCKED: {reason}",
                error=reason,
                duration_seconds=time.time() - start,
            )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, prefix="nanobot_"
        ) as f:
            f.write(textwrap.dedent(code))
            tmp_path = f.name

        try:
            # Using create_subprocess_exec (not shell) for safe execution
            proc = await asyncio.create_subprocess_exec(
                "python3",
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=CODE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    output=f"TIMEOUT: Code exceeded {CODE_TIMEOUT_SECONDS}s limit",
                    error="timeout",
                    duration_seconds=CODE_TIMEOUT_SECONDS,
                )

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()
            success = proc.returncode == 0

            output_parts = []
            if description:
                output_parts.append(f"Code: {description}")
            if stdout_str:
                output_parts.append(f"STDOUT:\n{stdout_str}")
            if stderr_str:
                output_parts.append(f"STDERR:\n{stderr_str}")
            output_parts.append(f"Exit code: {proc.returncode}")

            return ToolResult(
                tool_name=self.name,
                success=success,
                output="\n\n".join(output_parts),
                raw={
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "returncode": proc.returncode,
                },
                duration_seconds=time.time() - start,
            )

        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Execution error: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )
        finally:
            os.unlink(tmp_path)
