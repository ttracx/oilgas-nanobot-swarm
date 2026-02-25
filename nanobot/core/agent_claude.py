"""
NanobotClaude — Claude-backed agent with full tool use.

Drop-in replacement for NanobotV3 when using the Anthropic API.
Supports:
- Claude's native tool_use message format
- Persistent Redis memory + task journaling
- Knowledge graph injection
- Swarm registry integration
"""

import os
import time
import uuid
import structlog
from anthropic import AsyncAnthropic

from nanobot.core.agent import AgentConfig, AgentTask, AgentResult, AgentStatus
from nanobot.tools.base import ToolRegistry
from nanobot.tools.anthropic_router import AnthropicRouter
from nanobot.core.agent_v2 import build_default_registry
from nanobot.state.memory_store import AgentMemoryStore
from nanobot.state.task_journal import TaskJournal
from nanobot.state.swarm_state import SwarmStateManager

log = structlog.get_logger()

swarm_state = SwarmStateManager()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


def _build_anthropic_client() -> AsyncAnthropic:
    """Build Anthropic async client with proper timeout config."""
    return AsyncAnthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=600.0,
        max_retries=0,  # We handle retries in the router
    )


class NanobotClaude:
    """
    Claude-backed nanobot with full tool use, Redis memory, and task journaling.
    Uses AnthropicRouter for the agentic loop instead of vLLM ToolRouter.
    """

    def __init__(
        self,
        config: AgentConfig,
        session_id: str,
        tool_registry: ToolRegistry | None = None,
        anthropic_client: AsyncAnthropic | None = None,
    ):
        self.id = str(uuid.uuid4())
        self.config = config
        self.session_id = session_id
        self.status = AgentStatus.IDLE

        self.client = anthropic_client or _build_anthropic_client()
        registry = tool_registry or build_default_registry()
        self.router = AnthropicRouter(self.client, registry)
        self.memory = AgentMemoryStore(self.id, config.role.value)
        self.journal = TaskJournal(session_id)

    async def initialize(self) -> None:
        await swarm_state.register_agent(
            agent_id=self.id,
            role=self.config.role.value,
            name=self.config.name,
            session_id=self.session_id,
        )
        log.info("nanobot_claude_registered", id=self.id, role=self.config.role)

    async def _build_messages(self, task: AgentTask) -> tuple[str, list[dict]]:
        """
        Build system prompt and messages for Claude.
        Returns (system_prompt, messages) since Anthropic takes system separately.
        """
        memory_ctx = await self.memory.build_memory_context()
        system_prompt = memory_ctx + self.config.system_prompt

        messages = []

        # Inject conversation history
        history = await self.memory.get_conversation_history(last_n=10)
        for h in history:
            if h.get("role") in ("user", "assistant"):
                messages.append({"role": h["role"], "content": h["content"]})

        # Inject dependency results as context
        if task.context.get("dep_results"):
            dep_text = "\n\n".join([
                f"[Dependency {k}]: {v}"
                for k, v in task.context["dep_results"].items()
            ])
            messages.append({
                "role": "user",
                "content": f"Context from completed dependencies:\n{dep_text}",
            })
            messages.append({
                "role": "assistant",
                "content": "Understood. I'll use this context in my response.",
            })

        # Main task
        messages.append({"role": "user", "content": task.content})

        return system_prompt, messages

    async def execute(self, task: AgentTask) -> AgentResult:
        start = time.time()
        self.status = AgentStatus.THINKING
        await swarm_state.update_agent_status(self.id, "thinking")

        await self.journal.record_task_start(
            task_id=task.id,
            agent_id=self.id,
            agent_role=self.config.role.value,
            content=task.content,
            parent_task_id=task.parent_task_id,
        )

        try:
            system_prompt, messages = await self._build_messages(task)
            self.status = AgentStatus.EXECUTING
            await swarm_state.update_agent_status(self.id, "executing")

            final_text, updated_messages, total_tokens = await self.router.run_with_tools(
                messages=messages,
                model=ANTHROPIC_MODEL,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_prompt,
            )

            duration = time.time() - start

            await self.memory.push_conversation_turn("user", task.content)
            await self.memory.push_conversation_turn("assistant", final_text)

            # Count tool calls from the conversation
            tool_calls_made = []
            for m in updated_messages:
                if m.get("role") == "user" and isinstance(m.get("content"), list):
                    for block in m["content"]:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tool_calls_made.append(block.get("tool_use_id", ""))

            await self.journal.record_task_complete(
                task_id=task.id,
                output=final_text,
                success=True,
                tokens_used=total_tokens,
                duration_seconds=duration,
                tool_calls=tool_calls_made,
            )

            await swarm_state.update_agent_status(
                self.id, "idle", tokens_delta=total_tokens
            )

            self.status = AgentStatus.DONE
            log.info(
                "nanobot_claude_done",
                id=self.id,
                duration=f"{duration:.2f}s",
                tokens=total_tokens,
                model=ANTHROPIC_MODEL,
            )

            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                agent_role=self.config.role,
                output=final_text,
                success=True,
                duration_seconds=duration,
                tokens_used=total_tokens,
            )

        except Exception as e:
            duration = time.time() - start
            self.status = AgentStatus.FAILED
            await swarm_state.update_agent_status(self.id, "failed")
            await self.journal.record_task_complete(
                task_id=task.id,
                output="",
                success=False,
                duration_seconds=duration,
            )
            log.error("nanobot_claude_failed", id=self.id, error=str(e))
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                agent_role=self.config.role,
                output="",
                success=False,
                error=str(e),
                duration_seconds=duration,
            )

    async def store_long_term_fact(self, key: str, value: str) -> None:
        await self.memory.store_fact(key, value)

    async def shutdown(self) -> None:
        await swarm_state.deregister_agent(self.id)
        self.status = AgentStatus.IDLE

    def reset(self):
        self.status = AgentStatus.IDLE
