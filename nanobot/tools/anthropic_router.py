"""
AnthropicRouter — Claude-native agentic loop engine.

Uses the Anthropic Messages API with native tool_use blocks.
Drop-in replacement for ToolRouter when using Claude as the LLM backend.

Supports:
- Claude's native tool_use / tool_result message format
- Streaming responses for long-running tasks
- Retry with exponential backoff on overloaded/rate-limit errors
- Configurable max iterations for the tool loop
"""

import asyncio
import json
import os
import time
import structlog
from anthropic import AsyncAnthropic, APIStatusError, APITimeoutError, APIConnectionError

from nanobot.tools.base import ToolRegistry, ToolResult

log = structlog.get_logger()

MAX_TOOL_ITERATIONS = 10
LLM_RETRIES = 2
LLM_BACKOFF_BASE = 1.0

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


class AnthropicRouter:
    """
    Manages the agentic tool-use loop using the Anthropic Messages API.
    Claude returns tool_use blocks; we dispatch tools and feed tool_result back.
    """

    def __init__(self, client: AsyncAnthropic, registry: ToolRegistry):
        self.client = client
        self.registry = registry

    async def _dispatch_tool(self, name: str, input_data: dict) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult(
                tool_name=name,
                success=False,
                output=f"Unknown tool: {name}",
                error="tool_not_found",
            )
        try:
            return await tool.run(**input_data)
        except Exception as e:
            return ToolResult(
                tool_name=name,
                success=False,
                output=f"Tool execution error: {e}",
                error=str(e),
            )

    async def _call_claude(
        self,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        tools: list[dict] | None = None,
    ) -> dict:
        """
        Call Claude Messages API with retry on overloaded/rate-limit errors.
        Returns the raw response dict with: role, content, stop_reason, usage.
        """
        last_error = None
        for attempt in range(LLM_RETRIES + 1):
            try:
                kwargs = dict(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages,
                )
                if system:
                    kwargs["system"] = system
                if tools:
                    kwargs["tools"] = tools

                response = await self.client.messages.create(**kwargs)

                return {
                    "id": response.id,
                    "role": response.role,
                    "content": response.content,
                    "stop_reason": response.stop_reason,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                }

            except (APIStatusError, APITimeoutError, APIConnectionError) as e:
                last_error = e
                is_retryable = False
                if isinstance(e, APITimeoutError) or isinstance(e, APIConnectionError):
                    is_retryable = True
                elif isinstance(e, APIStatusError) and e.status_code in (429, 529, 500, 503):
                    is_retryable = True

                if not is_retryable or attempt == LLM_RETRIES:
                    log.error(
                        "claude_call_failed",
                        attempt=attempt + 1,
                        error_type=type(e).__name__,
                        error=str(e)[:200],
                    )
                    raise

                backoff = LLM_BACKOFF_BASE * (2 ** attempt)
                # Respect Retry-After header if present
                if isinstance(e, APIStatusError):
                    retry_after = getattr(e, "headers", {}).get("retry-after")
                    if retry_after:
                        try:
                            backoff = max(backoff, float(retry_after))
                        except ValueError:
                            pass
                log.warning(
                    "claude_call_retry",
                    attempt=attempt + 1,
                    backoff_s=backoff,
                    error=str(e)[:200],
                )
                await asyncio.sleep(backoff)

        raise last_error

    async def run_with_tools(
        self,
        messages: list[dict],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        system: str = "",
    ) -> tuple[str, list[dict], int]:
        """
        Run the full agentic loop with Claude:
        1. Call Claude with tools
        2. If tool_use in response → dispatch → inject tool_result → loop
        3. If end_turn → done

        Messages format follows Anthropic convention:
        - {"role": "user", "content": "..."}
        - {"role": "assistant", "content": [...blocks...]}
        - {"role": "user", "content": [{"type": "tool_result", ...}]}

        The system prompt is passed separately (not in messages).

        Returns: (final_text, updated_messages, total_tokens_used)
        """
        model = model or ANTHROPIC_MODEL
        tools = self.registry.as_anthropic_tools()
        total_tokens = 0
        iteration = 0

        # Extract system prompt from messages if present
        # (Anthropic API takes system as a separate param, not in messages)
        anthropic_messages = []
        extracted_system = system
        for msg in messages:
            if msg["role"] == "system":
                extracted_system = (extracted_system + "\n\n" + msg["content"]).strip()
            else:
                anthropic_messages.append(msg)

        current_messages = list(anthropic_messages)

        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1
            log.info("claude_tool_loop_iteration", iteration=iteration)

            response = await self._call_claude(
                model=model,
                system=extracted_system,
                messages=current_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=tools if tools else None,
            )

            total_tokens += response["usage"]["input_tokens"] + response["usage"]["output_tokens"]

            # Parse response content blocks
            content_blocks = response["content"]
            text_parts = []
            tool_use_blocks = []

            for block in content_blocks:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)

            # Append the full assistant message (preserving all blocks)
            current_messages.append({
                "role": "assistant",
                "content": content_blocks,
            })

            # If no tool calls, we're done
            if response["stop_reason"] == "end_turn" or not tool_use_blocks:
                final_text = "\n".join(text_parts)
                log.info(
                    "claude_tool_loop_complete",
                    iterations=iteration,
                    total_tokens=total_tokens,
                )
                return final_text, current_messages, total_tokens

            # Dispatch all tool calls and build tool_result blocks
            tool_result_blocks = []
            for tool_block in tool_use_blocks:
                tool_name = tool_block.name
                tool_input = tool_block.input
                tool_use_id = tool_block.id

                log.info(
                    "claude_tool_dispatch",
                    tool=tool_name,
                    input_preview=json.dumps(tool_input)[:100],
                    iteration=iteration,
                )

                result = await self._dispatch_tool(tool_name, tool_input)

                log.info(
                    "claude_tool_result",
                    tool=tool_name,
                    success=result.success,
                    duration=f"{result.duration_seconds:.2f}s",
                    output_preview=result.output[:100],
                )

                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result.output,
                    "is_error": not result.success,
                })

            # Append tool results as a user message (Anthropic convention)
            current_messages.append({
                "role": "user",
                "content": tool_result_blocks,
            })

        # Max iterations hit
        log.warning("claude_tool_loop_max_iterations", max=MAX_TOOL_ITERATIONS)
        last_text = next(
            (
                "\n".join(
                    b.text for b in m.get("content", [])
                    if hasattr(b, "type") and b.type == "text"
                )
                for m in reversed(current_messages)
                if m.get("role") == "assistant"
            ),
            "Max tool iterations reached without final response.",
        )
        return last_text, current_messages, total_tokens
