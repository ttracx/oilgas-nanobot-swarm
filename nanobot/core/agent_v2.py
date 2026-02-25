"""
Nanobot v2 — tool-use enabled agent.
Drop-in replacement for agent.py with full agentic loop support.
"""

import time
import uuid
import structlog
from openai import AsyncOpenAI

from nanobot.core.agent import AgentConfig, AgentTask, AgentResult, AgentStatus, AgentRole
from nanobot.tools.base import ToolRegistry
from nanobot.tools.router import ToolRouter
from nanobot.tools.web_search import WebSearchTool
from nanobot.tools.code_runner import CodeRunnerTool
from nanobot.tools.file_io import FileIOTool
from nanobot.tools.http_fetch import HttpFetchTool
from nanobot.tools.knowledge_tools import register_knowledge_tools
from nanobot.tools.msgraph_tools import register_msgraph_tools

log = structlog.get_logger()


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(WebSearchTool())
    registry.register(CodeRunnerTool())
    registry.register(FileIOTool())
    registry.register(HttpFetchTool())
    register_knowledge_tools(registry)
    register_msgraph_tools(registry)
    return registry


class NanobotV2:
    """Tool-use enabled nanobot with full agentic loop."""

    def __init__(
        self,
        config: AgentConfig,
        vllm_base_url: str = "http://localhost:8000/v1",
        api_key: str = "nq-nanobot",
        tool_registry: ToolRegistry | None = None,
    ):
        self.id = str(uuid.uuid4())
        self.config = config
        self.status = AgentStatus.IDLE
        self.conversation_history: list[dict] = []

        self.client = AsyncOpenAI(
            base_url=vllm_base_url,
            api_key=api_key,
            timeout=config.timeout_seconds,
        )

        registry = tool_registry or build_default_registry()
        self.router = ToolRouter(self.client, registry)

        log.info("nanobot_v2_init", id=self.id, role=config.role, name=config.name)

    def _build_messages(self, task: AgentTask) -> list[dict]:
        messages = [{"role": "system", "content": self.config.system_prompt}]
        if task.context.get("conversation_history"):
            messages.extend(task.context["conversation_history"])
        messages.append({"role": "user", "content": task.content})
        return messages

    async def execute(self, task: AgentTask) -> AgentResult:
        start = time.time()
        self.status = AgentStatus.THINKING

        log.info(
            "nanobot_v2_execute",
            agent_id=self.id,
            role=self.config.role,
            task_id=task.id,
        )

        try:
            messages = self._build_messages(task)
            self.status = AgentStatus.EXECUTING

            final_text, updated_messages, total_tokens = await self.router.run_with_tools(
                messages=messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
            )

            self.conversation_history.extend(updated_messages[len(messages):])

            duration = time.time() - start
            self.status = AgentStatus.DONE

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
            self.status = AgentStatus.FAILED
            log.error("nanobot_v2_failed", agent_id=self.id, error=str(e))
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                agent_role=self.config.role,
                output="",
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    def reset(self):
        self.status = AgentStatus.IDLE
        self.conversation_history.clear()
