"""
NeuralQuantum Nanobot Agent Core
Single agent unit in the swarm — connects to vLLM, executes tasks,
reports results to orchestrator.
"""

import asyncio
import os
import uuid
import time
import structlog
import httpx
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()


class AgentRole(str, Enum):
    # L0
    ORCHESTRATOR = "orchestrator"
    # L1
    RESEARCHER = "researcher"
    CODER = "coder"
    ANALYST = "analyst"
    VALIDATOR = "validator"
    EXECUTOR = "executor"
    ARCHITECT = "architect"
    # L2 — Coder sub-swarm
    CODE_PLANNER = "code_planner"
    CODE_WRITER = "code_writer"
    CODE_TESTER = "code_tester"
    CODE_REVIEWER = "code_reviewer"
    # L2 — Researcher sub-swarm
    WEB_SEARCHER = "web_searcher"
    SYNTHESIZER = "synthesizer"
    FACT_VERIFIER = "fact_verifier"
    # L2 — Analyst sub-swarm
    REASONER = "reasoner"
    CRITIQUER = "critiquer"
    SUMMARIZER = "summarizer"
    # L2 — Validator sub-swarm
    CORRECTNESS = "correctness"
    COMPLETENESS = "completeness"
    SCORER = "scorer"
    # L2 — Executor sub-swarm
    ACTION_PLANNER = "action_planner"
    ACTION_RUNNER = "action_runner"


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"


@dataclass
class AgentConfig:
    role: AgentRole
    name: str
    system_prompt: str
    max_tokens: int = 2048
    temperature: float = 0.1
    top_p: float = 0.95
    max_retries: int = 3
    timeout_seconds: float = 300.0


@dataclass
class AgentTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    parent_task_id: Optional[str] = None
    priority: int = 5
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentResult:
    task_id: str
    agent_id: str
    agent_role: AgentRole
    output: str
    success: bool
    error: Optional[str] = None
    duration_seconds: float = 0.0
    tokens_used: int = 0
    timestamp: float = field(default_factory=time.time)


class Nanobot:
    """Single nanobot agent — the atomic unit of the swarm."""

    def __init__(
        self,
        config: AgentConfig,
        vllm_base_url: str = "http://localhost:8000/v1",
        api_key: str = "nq-nanobot",
    ):
        self.id = str(uuid.uuid4())
        self.config = config
        self.status = AgentStatus.IDLE
        self.conversation_history: list[dict] = []
        self.results: list[AgentResult] = []

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

        log.info("nanobot_init", id=self.id, role=config.role, name=config.name)

    def _build_messages(self, task: AgentTask) -> list[dict]:
        messages = [{"role": "system", "content": self.config.system_prompt}]
        if task.context.get("conversation_history"):
            messages.extend(task.context["conversation_history"])
        messages.append({"role": "user", "content": task.content})
        return messages

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_llm(self, messages: list[dict]) -> tuple[str, int]:
        """Call LLM with streaming to keep connections alive for cloud models."""
        content_parts: list[str] = []
        total_tokens = 0

        kwargs = dict(
            model=os.getenv("SWARM_MODEL", "nanobot-reasoner"),
            messages=messages,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            stream=True,
            stream_options={"include_usage": True},
        )

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except Exception:
            # Fallback: some backends don't support stream_options
            kwargs.pop("stream_options", None)
            stream = await self.client.chat.completions.create(**kwargs)

        async for chunk in stream:
            if chunk.usage:
                total_tokens = chunk.usage.total_tokens
            if chunk.choices and chunk.choices[0].delta.content:
                content_parts.append(chunk.choices[0].delta.content)

        return "".join(content_parts), total_tokens

    async def execute(self, task: AgentTask) -> AgentResult:
        start_time = time.time()
        self.status = AgentStatus.THINKING

        log.info(
            "nanobot_execute_start",
            agent_id=self.id,
            role=self.config.role,
            task_id=task.id,
            task_preview=task.content[:100],
        )

        try:
            messages = self._build_messages(task)
            self.status = AgentStatus.EXECUTING
            output, tokens = await self._call_llm(messages)

            self.conversation_history.append({"role": "user", "content": task.content})
            self.conversation_history.append({"role": "assistant", "content": output})

            duration = time.time() - start_time
            result = AgentResult(
                task_id=task.id,
                agent_id=self.id,
                agent_role=self.config.role,
                output=output,
                success=True,
                duration_seconds=duration,
                tokens_used=tokens,
            )
            self.status = AgentStatus.DONE
            log.info(
                "nanobot_execute_done",
                agent_id=self.id,
                duration=f"{duration:.2f}s",
                tokens=tokens,
            )
            return result

        except Exception as e:
            duration = time.time() - start_time
            self.status = AgentStatus.FAILED
            log.error("nanobot_execute_failed", agent_id=self.id, error=str(e))
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                agent_role=self.config.role,
                output="",
                success=False,
                error=str(e),
                duration_seconds=duration,
            )

    def reset(self):
        self.status = AgentStatus.IDLE
        self.conversation_history.clear()
