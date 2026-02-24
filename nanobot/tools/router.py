"""
ToolRouter — the agentic loop engine.
Intercepts tool calls from vLLM, dispatches to tools, feeds results back.
Implements the full tool-use loop inside each nanobot's execute cycle.
"""

import json
import time
import structlog
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from nanobot.tools.base import ToolRegistry, ToolResult

log = structlog.get_logger()

MAX_TOOL_ITERATIONS = 10


class ToolRouter:
    """
    Manages the agentic tool-use loop for a nanobot.
    Wraps the vLLM client and handles function calling transparently.
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

    async def run_with_tools(
        self,
        messages: list[dict],
        model: str = "nanobot-reasoner",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        top_p: float = 0.95,
    ) -> tuple[str, list[dict], int]:
        """
        Run the full agentic loop:
        1. Call LLM
        2. If tool call -> dispatch -> inject result -> loop
        3. If text response -> done

        Returns: (final_text, updated_messages, total_tokens_used)
        """
        tools = self.registry.as_openai_functions()
        current_messages = list(messages)
        total_tokens = 0
        iteration = 0

        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1
            log.info("tool_loop_iteration", iteration=iteration)

            try:
                response: ChatCompletion = await self.client.chat.completions.create(
                    model=model,
                    messages=current_messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                )
            except Exception as e:
                # If tool_choice not supported, fall back to no-tools call
                log.warning("tool_call_fallback", error=str(e))
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=current_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                )

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
