"""
ToolRouter — the agentic loop engine.
Intercepts tool calls from vLLM, dispatches to tools, feeds results back.
Implements the full tool-use loop inside each nanobot's execute cycle.

Hardened for Ollama cloud models:
- Streaming by default (keeps connections alive past gateway timeouts)
- Retry with exponential backoff on timeout/connection errors
- Structured error telemetry (connect vs read vs proxy)
"""

import asyncio
import json
import os
import time
import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from nanobot.tools.base import ToolRegistry, ToolResult

log = structlog.get_logger()

MAX_TOOL_ITERATIONS = 10
LLM_RETRIES = 2
LLM_BACKOFF_BASE = 1.0  # seconds — retries at 1s, 2s
SWARM_MODEL = os.getenv("SWARM_MODEL", "nanobot-reasoner")


class ToolRouter:
    """
    Manages the agentic tool-use loop for a nanobot.
    Wraps the vLLM client and handles function calling transparently.
    Uses streaming + retry for resilience with cloud models.
    """

    def __init__(self, client: AsyncOpenAI, registry: ToolRegistry):
        self.client = client
        self.registry = registry

    async def _dispatch_tool(self, name: str, args_str: str) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult(
                tool_name=name,
                success=False,
                output=f"Unknown tool: {name}",
                error="tool_not_found",
            )
        try:
            args = json.loads(args_str) if args_str else {}
            return await tool.run(**args)
        except json.JSONDecodeError as e:
            return ToolResult(
                tool_name=name,
                success=False,
                output=f"Invalid tool arguments JSON: {e}",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                tool_name=name,
                success=False,
                output=f"Tool execution error: {e}",
                error=str(e),
            )

    async def _call_llm_streaming(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        top_p: float,
        tools: list | None = None,
    ) -> ChatCompletion:
        """
        Call LLM with streaming to keep connections alive, then reassemble
        into a ChatCompletion-like object. Falls back to non-streaming on error.

        Retries on timeout/connection errors with exponential backoff.
        """
        last_error = None
        for attempt in range(LLM_RETRIES + 1):
            try:
                return await self._call_llm_streaming_inner(
                    model, messages, max_tokens, temperature, top_p, tools
                )
            except Exception as e:
                last_error = e
                error_type = type(e).__name__
                is_retryable = any(
                    kw in error_type.lower() or kw in str(e).lower()
                    for kw in ("timeout", "connect", "reset", "closed", "eof", "broken")
                )
                if not is_retryable or attempt == LLM_RETRIES:
                    log.error(
                        "llm_call_failed",
                        attempt=attempt + 1,
                        error_type=error_type,
                        error=str(e)[:200],
                        retryable=is_retryable,
                    )
                    raise
                backoff = LLM_BACKOFF_BASE * (2 ** attempt)
                log.warning(
                    "llm_call_retry",
                    attempt=attempt + 1,
                    backoff_s=backoff,
                    error_type=error_type,
                    error=str(e)[:200],
                )
                await asyncio.sleep(backoff)
        raise last_error  # unreachable but satisfies type checker

    async def _call_llm_streaming_inner(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        top_p: float,
        tools: list | None,
    ) -> ChatCompletion:
        """Stream chunks from LLM and reassemble into a ChatCompletion."""
        kwargs = dict(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            # Some backends don't support stream_options — retry without
            if "stream_options" in str(e):
                kwargs.pop("stream_options", None)
                stream = await self.client.chat.completions.create(**kwargs)
            else:
                raise

        # Accumulate streamed chunks
        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}  # index -> {id, name, arguments}
        finish_reason = None
        usage = None
        model_id = model

        async for chunk in stream:
            if chunk.model:
                model_id = chunk.model
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            if delta.content:
                content_parts.append(delta.content)

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        tool_calls_acc[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_acc[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

        # Reassemble into ChatCompletion
        from openai.types.chat.chat_completion import ChatCompletion, Choice
        from openai.types.chat.chat_completion_message import ChatCompletionMessage
        from openai.types.chat.chat_completion_message_tool_call import (
            ChatCompletionMessageToolCall,
            Function,
        )
        from openai.types.completion_usage import CompletionUsage

        assembled_tool_calls = None
        if tool_calls_acc:
            assembled_tool_calls = [
                ChatCompletionMessageToolCall(
                    id=tc["id"],
                    type="function",
                    function=Function(name=tc["name"], arguments=tc["arguments"]),
                )
                for tc in sorted(tool_calls_acc.values(), key=lambda t: t["id"])
            ]

        message = ChatCompletionMessage(
            role="assistant",
            content="".join(content_parts) or None,
            tool_calls=assembled_tool_calls,
        )

        assembled_usage = None
        if usage:
            assembled_usage = usage

        return ChatCompletion(
            id=f"stream-{int(time.time())}",
            created=int(time.time()),
            model=model_id,
            object="chat.completion",
            choices=[
                Choice(
                    index=0,
                    message=message,
                    finish_reason=finish_reason or "stop",
                )
            ],
            usage=assembled_usage,
        )

    async def run_with_tools(
        self,
        messages: list[dict],
        model: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        top_p: float = 0.95,
    ) -> tuple[str, list[dict], int]:
        """
        Run the full agentic loop:
        1. Call LLM (streaming + retry)
        2. If tool call -> dispatch -> inject result -> loop
        3. If text response -> done

        Returns: (final_text, updated_messages, total_tokens_used)
        """
        model = model or SWARM_MODEL
        tools = self.registry.as_openai_functions()
        current_messages = list(messages)
        total_tokens = 0
        iteration = 0

        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1
            log.info("tool_loop_iteration", iteration=iteration)

            try:
                response = await self._call_llm_streaming(
                    model=model,
                    messages=current_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    tools=tools if tools else None,
                )
            except Exception as e:
                # If tools caused the error, fall back to no-tools call
                if tools:
                    log.warning("tool_call_fallback", error=str(e)[:200])
                    response = await self._call_llm_streaming(
                        model=model,
                        messages=current_messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        tools=None,
                    )
                else:
                    raise

            if response.usage:
                total_tokens += response.usage.total_tokens

            choice = response.choices[0]
            message: ChatCompletionMessage = choice.message

            current_messages.append(message.model_dump(exclude_none=True))

            if choice.finish_reason == "stop" or not message.tool_calls:
                final_text = message.content or ""
                log.info(
                    "tool_loop_complete",
                    iterations=iteration,
                    total_tokens=total_tokens,
                )
                return final_text, current_messages, total_tokens

            tool_results_messages = []
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = tool_call.function.arguments
                call_id = tool_call.id

                log.info(
                    "tool_call_dispatch",
                    tool=fn_name,
                    args_preview=fn_args[:100],
                    iteration=iteration,
                )

                result = await self._dispatch_tool(fn_name, fn_args)

                log.info(
                    "tool_call_result",
                    tool=fn_name,
                    success=result.success,
                    duration=f"{result.duration_seconds:.2f}s",
                    output_preview=result.output[:100],
                )

                tool_results_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result.output,
                    }
                )

            current_messages.extend(tool_results_messages)

        log.warning("tool_loop_max_iterations", max=MAX_TOOL_ITERATIONS)
        last_content = next(
            (
                m.get("content", "")
                for m in reversed(current_messages)
                if m.get("role") == "assistant" and m.get("content")
            ),
            "Max tool iterations reached without final response.",
        )
        return last_content, current_messages, total_tokens
