"""
Nanobot v3 — full Redis state integration.
Tool use (v2) + persistent memory + task journaling + swarm registry.
"""

import time
import uuid
import structlog
import httpx
from openai import AsyncOpenAI

from nanobot.core.agent import AgentConfig, AgentTask, AgentResult, AgentStatus
from nanobot.tools.base import ToolRegistry
from nanobot.tools.router import ToolRouter
from nanobot.core.agent_v2 import build_default_registry
from nanobot.state.memory_store import AgentMemoryStore
from nanobot.state.task_journal import TaskJournal
from nanobot.state.swarm_state import SwarmStateManager

log = structlog.get_logger()

swarm_state = SwarmStateManager()


class NanobotV3:
    """
    Full-capability nanobot:
    - Tool use (web search, code, file I/O, HTTP)
    - Persistent Redis memory (short/long/episodic)
    - Task journaling + audit trail
    - Swarm registry integration
    """

    def __init__(
        self,
        config: AgentConfig,
        session_id: str,
        vllm_base_url: str = "http://localhost:8000/v1",
        api_key: str = "nq-nanobot",
        tool_registry: ToolRegistry | None = None,
    ):
        self.id = str(uuid.uuid4())
        self.config = config
        self.session_id = session_id
        self.status = AgentStatus.IDLE

        self.client = AsyncOpenAI(
            base_url=vllm_base_url,
            api_key=api_key,
            timeout=httpx.Timeout(
                connect=30.0,
                read=max(config.timeout_seconds, 600.0),
                write=60.0,
                pool=60.0,
            ),
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=max(config.timeout_seconds, 600.0),
                    write=60.0,
                    pool=60.0,
                ),
                http2=True,
            ),
        )

        registry = tool_registry or build_default_registry()
        self.router = ToolRouter(self.client, registry)
        self.memory = AgentMemoryStore(self.id, config.role.value)
        self.journal = TaskJournal(session_id)

    async def initialize(self) -> None:
        await swarm_state.register_agent(
            agent_id=self.id,
            role=self.config.role.value,
            name=self.config.name,
            session_id=self.session_id,
        )
        log.info("nanobot_v3_registered", id=self.id, role=self.config.role)

    async def _build_messages(self, task: AgentTask) -> list[dict]:
        memory_ctx = await self.memory.build_memory_context()
        system_content = memory_ctx + self.config.system_prompt

        messages = [{"role": "system", "content": system_content}]

        history = await self.memory.get_conversation_history(last_n=10)
        messages.extend(history)

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

        messages.append({"role": "user", "content": task.content})
        return messages

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
            messages = await self._build_messages(task)
            self.status = AgentStatus.EXECUTING
            await swarm_state.update_agent_status(self.id, "executing")

            final_text, updated_messages, total_tokens = await self.router.run_with_tools(
                messages=messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
            )

            duration = time.time() - start

            await self.memory.push_conversation_turn("user", task.content)
            await self.memory.push_conversation_turn("assistant", final_text)

            tool_calls_made = [
                m.get("name", "")
                for m in updated_messages
                if m.get("role") == "tool"
            ]

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
                "nanobot_v3_done",
                id=self.id,
                duration=f"{duration:.2f}s",
                tokens=total_tokens,
                tools_used=tool_calls_made,
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
            log.error("nanobot_v3_failed", id=self.id, error=str(e))
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
