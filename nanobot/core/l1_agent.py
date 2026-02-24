"""
L1 Agent — primary domain specialist that commands its own sub-swarm.
"""

import time
import uuid
import asyncio
import structlog

from nanobot.core.roles import L1Role
from nanobot.core.sub_swarm import SubSwarm
from nanobot.core.agent import AgentTask, AgentResult, AgentStatus, AgentConfig, AgentRole
from nanobot.core.agent_v3 import NanobotV3, swarm_state
from nanobot.tools.base import ToolRegistry
from nanobot.core.agent_v2 import build_default_registry

log = structlog.get_logger()

L1_SYSTEM_PROMPTS: dict[L1Role, str] = {
    L1Role.CODER: """You are the Lead Coder in the NeuralQuantum Nanobot Swarm.
You coordinate a sub-swarm of: Code Planner, Code Writer, Code Tester, and Code Reviewer.
Your sub-swarm handles full implementation pipelines automatically.
Your role: interpret the coding task, add architectural context, review final output for coherence.
Focus on: design patterns, module boundaries, integration points.""",

    L1Role.RESEARCHER: """You are the Lead Researcher in the NeuralQuantum Nanobot Swarm.
You coordinate a sub-swarm of: Web Searcher, Synthesizer, and Fact Verifier.
Your sub-swarm handles search, synthesis, and verification automatically.
Your role: define the research scope, evaluate quality of findings, flag knowledge gaps.""",

    L1Role.ANALYST: """You are the Lead Analyst in the NeuralQuantum Nanobot Swarm.
You coordinate a sub-swarm of: Reasoner, Critiquer, and Summarizer.
Your sub-swarm handles full analytical pipelines automatically.
Your role: frame the analysis question correctly, evaluate reasoning quality, contextualize conclusions.""",

    L1Role.VALIDATOR: """You are the Lead Validator in the NeuralQuantum Nanobot Swarm.
You coordinate a sub-swarm of: Correctness, Completeness, and Scorer sub-agents.
Your sub-swarm runs validation checks automatically.
Your role: set validation criteria, interpret scores, decide pass/fail, recommend improvements.""",

    L1Role.EXECUTOR: """You are the Lead Executor in the NeuralQuantum Nanobot Swarm.
You coordinate a sub-swarm of: Action Planner and Action Runner.
Your sub-swarm handles action sequencing and execution automatically.
Your role: define success criteria, monitor execution, handle blockers.""",

    L1Role.ARCHITECT: """You are the Systems Architect in the NeuralQuantum Nanobot Swarm.
You operate solo — no sub-swarm.
Your specialty: system design, architecture decisions, technology selection, integration patterns.
Output: architecture diagrams (text), decision rationale, tradeoff analysis, implementation roadmap.""",
}


class L1Agent:
    """L1 Domain Agent — commands a SubSwarm of L2 agents."""

    def __init__(
        self,
        role: L1Role,
        session_id: str,
        vllm_url: str = "http://localhost:8000/v1",
        api_key: str = "nq-nanobot",
        tool_registry: ToolRegistry | None = None,
        global_semaphore: asyncio.Semaphore | None = None,
    ):
        self.role = role
        self.session_id = session_id
        self.id = str(uuid.uuid4())
        self.status = AgentStatus.IDLE
        self.registry = tool_registry or build_default_registry()
        self.global_semaphore = global_semaphore or asyncio.Semaphore(16)

        self.self_agent = NanobotV3(
            config=AgentConfig(
                role=AgentRole(role.value),
                name=f"{role.value}-lead-{uuid.uuid4().hex[:6]}",
                system_prompt=L1_SYSTEM_PROMPTS[role],
                max_tokens=2048,
                temperature=0.05,
            ),
            session_id=session_id,
            vllm_base_url=vllm_url,
            api_key=api_key,
            tool_registry=self.registry,
        )

        self.sub_swarm = SubSwarm(
            l1_role=role,
            session_id=session_id,
            vllm_url=vllm_url,
            api_key=api_key,
            tool_registry=self.registry,
            semaphore=self.global_semaphore,
        )

        log.info("l1_agent_init", id=self.id, role=role.value)

    async def initialize(self) -> None:
        await self.self_agent.initialize()

    async def execute(self, task: AgentTask) -> AgentResult:
        start = time.time()
        self.status = AgentStatus.EXECUTING

        log.info(
            "l1_execute_start",
            id=self.id,
            role=self.role.value,
            task_preview=task.content[:100],
        )

        try:
            # Phase 1: L1 contextualizes the task
            context_task = AgentTask(
                content=(
                    f"Before delegating to your sub-swarm, analyze this task and provide:\n"
                    f"1. Key clarifications or scope definitions\n"
                    f"2. Specific constraints or requirements to emphasize\n"
                    f"3. Quality criteria for the final output\n\n"
                    f"TASK:\n{task.content}"
                ),
                context=task.context,
            )
            context_result = await self.self_agent.execute(context_task)
            context_enrichment = context_result.output if context_result.success else ""

            # Phase 2: Sub-swarm executes pipeline
            enriched_task = (
                f"{task.content}\n\n## L1 LEAD CONTEXT:\n{context_enrichment}"
                if context_enrichment
                else task.content
            )
            sub_result = await self.sub_swarm.execute(enriched_task)

            # Phase 3: L1 reviews sub-swarm output
            review_task = AgentTask(
                content=(
                    f"Your sub-swarm has completed the task. Review and enhance their output.\n\n"
                    f"ORIGINAL TASK:\n{task.content}\n\n"
                    f"SUB-SWARM OUTPUT:\n{sub_result['final_output']}\n\n"
                    f"Your job:\n"
                    f"1. Identify any gaps or issues\n"
                    f"2. Add your L1 expertise layer\n"
                    f"3. Produce the final polished output\n"
                    f"Output ONLY the final answer — no meta-commentary."
                ),
            )
            final_result = await self.self_agent.execute(review_task)

            duration = time.time() - start
            total_tokens = (
                context_result.tokens_used
                + sub_result.get("total_tokens", 0)
                + final_result.tokens_used
            )

            self.status = AgentStatus.DONE
            log.info(
                "l1_execute_done",
                id=self.id,
                role=self.role.value,
                duration=f"{duration:.2f}s",
                total_tokens=total_tokens,
            )

            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                agent_role=AgentRole(self.role.value),
                output=(
                    final_result.output
                    if final_result.success
                    else sub_result["final_output"]
                ),
                success=True,
                duration_seconds=duration,
                tokens_used=total_tokens,
            )

        except Exception as e:
            self.status = AgentStatus.FAILED
            log.error("l1_execute_failed", id=self.id, error=str(e))
            return AgentResult(
                task_id=task.id,
                agent_id=self.id,
                agent_role=AgentRole(self.role.value),
                output="",
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    async def shutdown(self) -> None:
        await self.self_agent.shutdown()
        self.status = AgentStatus.IDLE
