"""
SubSwarm — a mini orchestrator that each L1 agent uses to
manage its own team of L2 sub-agents.
"""

import asyncio
import uuid
import time
import structlog
from dataclasses import dataclass
from typing import Any

from nanobot.core.roles import L1Role, L2Role
from nanobot.core.sub_prompts import SUB_AGENT_PROMPTS
from nanobot.core.agent import AgentConfig, AgentRole, AgentTask, AgentResult, AgentStatus
from nanobot.core.agent_v3 import NanobotV3
from nanobot.tools.base import ToolRegistry

log = structlog.get_logger()

MAX_SUB_PARALLEL = 4


@dataclass
class SubTaskResult:
    role: L2Role
    output: str
    success: bool
    duration: float
    tokens: int


class SubSwarm:
    """Mini-swarm commanded by a single L1 agent."""

    def __init__(
        self,
        l1_role: L1Role,
        session_id: str,
        vllm_url: str,
        api_key: str,
        tool_registry: ToolRegistry,
        semaphore: asyncio.Semaphore,
    ):
        self.l1_role = l1_role
        self.session_id = session_id
        self.vllm_url = vllm_url
        self.api_key = api_key
        self.registry = tool_registry
        self.semaphore = semaphore
        self.sub_semaphore = asyncio.Semaphore(MAX_SUB_PARALLEL)

        self.pipelines: dict[L1Role, list[list[L2Role]]] = {
            L1Role.CODER: [
                [L2Role.CODE_PLANNER],
                [L2Role.CODE_WRITER],
                [L2Role.CODE_TESTER, L2Role.CODE_REVIEWER],
            ],
            L1Role.RESEARCHER: [
                [L2Role.WEB_SEARCHER],
                [L2Role.SYNTHESIZER, L2Role.FACT_VERIFIER],
            ],
            L1Role.ANALYST: [
                [L2Role.REASONER],
                [L2Role.CRITIQUER],
                [L2Role.SUMMARIZER],
            ],
            L1Role.VALIDATOR: [
                [L2Role.CORRECTNESS, L2Role.COMPLETENESS],
                [L2Role.SCORER],
            ],
            L1Role.EXECUTOR: [
                [L2Role.ACTION_PLANNER],
                [L2Role.ACTION_RUNNER],
            ],
            L1Role.ARCHITECT: [],
        }

    def _make_sub_agent(self, role: L2Role) -> NanobotV3:
        prompt = SUB_AGENT_PROMPTS.get(
            role, f"You are a {role.value} sub-agent. Complete your assigned task."
        )
        return NanobotV3(
            config=AgentConfig(
                role=AgentRole(role.value),
                name=f"{role.value}-{uuid.uuid4().hex[:6]}",
                system_prompt=prompt,
                max_tokens=2048,
                temperature=0.05,
                timeout_seconds=300.0,
            ),
            session_id=self.session_id,
            vllm_base_url=self.vllm_url,
            api_key=self.api_key,
            tool_registry=self.registry,
        )

    @staticmethod
    def _truncate(text: str, max_chars: int = 6000) -> str:
        """Truncate text to fit within context window budget."""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n\n[... truncated {len(text) - max_chars} chars]"

    def _build_sub_task_content(
        self,
        role: L2Role,
        original_task: str,
        stage_inputs: dict[L2Role, str],
    ) -> str:
        content_parts = [f"TASK:\n{self._truncate(original_task, 2000)}"]

        if stage_inputs:
            relevant = {r: o for r, o in stage_inputs.items() if r != role}
            if relevant:
                ctx = "\n\n".join([
                    f"### Output from {r.value}:\n{self._truncate(o, 4000)}"
                    for r, o in relevant.items()
                ])
                content_parts.append(f"PRIOR STAGE OUTPUTS:\n{ctx}")

        # Role-specific context injection
        injections = {
            L2Role.CODE_WRITER: (L2Role.CODE_PLANNER, "IMPLEMENTATION PLAN TO FOLLOW"),
            L2Role.CODE_TESTER: (L2Role.CODE_WRITER, "CODE TO TEST"),
            L2Role.SYNTHESIZER: (L2Role.WEB_SEARCHER, "RAW SEARCH RESULTS TO SYNTHESIZE"),
            L2Role.FACT_VERIFIER: (L2Role.SYNTHESIZER, "SYNTHESIZED CLAIMS TO VERIFY"),
            L2Role.CRITIQUER: (L2Role.REASONER, "REASONING TO CRITIQUE"),
            L2Role.ACTION_RUNNER: (L2Role.ACTION_PLANNER, "ACTION PLAN TO EXECUTE"),
        }

        if role in injections:
            dep_role, label = injections[role]
            if dep_role in stage_inputs:
                content_parts.append(f"{label}:\n{self._truncate(stage_inputs[dep_role], 5000)}")
        elif role == L2Role.SUMMARIZER and stage_inputs:
            all_prior = "\n\n".join(self._truncate(v, 3000) for v in stage_inputs.values())
            content_parts.append(f"CONTENT TO SUMMARIZE:\n{all_prior}")

        return "\n\n".join(content_parts)

    async def _run_sub_agent(
        self,
        role: L2Role,
        original_task: str,
        stage_inputs: dict[L2Role, str],
    ) -> SubTaskResult:
        async with self.semaphore:
            async with self.sub_semaphore:
                start = time.time()
                agent = self._make_sub_agent(role)
                await agent.initialize()

                content = self._build_sub_task_content(role, original_task, stage_inputs)
                task = AgentTask(id=str(uuid.uuid4()), content=content)

                result = await agent.execute(task)
                await agent.shutdown()

                return SubTaskResult(
                    role=role,
                    output=result.output if result.success else f"FAILED: {result.error}",
                    success=result.success,
                    duration=time.time() - start,
                    tokens=result.tokens_used,
                )

    async def execute(self, task_content: str) -> dict[str, Any]:
        pipeline = self.pipelines.get(self.l1_role, [])

        if not pipeline:
            return {
                "l1_role": self.l1_role.value,
                "stages": [],
                "final_output": task_content,
                "total_tokens": 0,
            }

        all_outputs: dict[L2Role, str] = {}
        stage_logs = []
        total_tokens = 0

        log.info(
            "sub_swarm_start",
            l1_role=self.l1_role,
            stages=len(pipeline),
            task_preview=task_content[:80],
        )

        for stage_idx, stage_roles in enumerate(pipeline):
            log.info(
                "sub_swarm_stage",
                stage=stage_idx + 1,
                roles=[r.value for r in stage_roles],
            )

            stage_coros = [
                self._run_sub_agent(role, task_content, all_outputs)
                for role in stage_roles
            ]
            stage_results: list[SubTaskResult] = await asyncio.gather(*stage_coros)

            stage_entry = {"stage": stage_idx + 1, "results": []}
            for res in stage_results:
                all_outputs[res.role] = res.output
                total_tokens += res.tokens
                stage_entry["results"].append({
                    "role": res.role.value,
                    "success": res.success,
                    "duration": round(res.duration, 2),
                    "tokens": res.tokens,
                    "output_preview": res.output[:200],
                })
            stage_logs.append(stage_entry)

        final_output = self._synthesize_pipeline_output(all_outputs)

        log.info(
            "sub_swarm_complete",
            l1_role=self.l1_role,
            total_tokens=total_tokens,
        )

        return {
            "l1_role": self.l1_role.value,
            "stages": stage_logs,
            "sub_agent_outputs": {r.value: o for r, o in all_outputs.items()},
            "final_output": final_output,
            "total_tokens": total_tokens,
        }

    def _synthesize_pipeline_output(self, outputs: dict[L2Role, str]) -> str:
        if self.l1_role == L1Role.CODER:
            code = outputs.get(L2Role.CODE_WRITER, "")
            tests = outputs.get(L2Role.CODE_TESTER, "")
            review = outputs.get(L2Role.CODE_REVIEWER, "")
            parts = ["## Implementation\n" + code]
            if tests:
                parts.append("## Test Results\n" + tests)
            if review:
                parts.append("## Code Review\n" + review)
            return "\n\n".join(parts)

        elif self.l1_role == L1Role.RESEARCHER:
            synthesis = outputs.get(L2Role.SYNTHESIZER, "")
            verification = outputs.get(L2Role.FACT_VERIFIER, "")
            parts = [synthesis]
            if verification:
                parts.append("## Fact Verification\n" + verification)
            return "\n\n".join(parts)

        elif self.l1_role == L1Role.ANALYST:
            return outputs.get(L2Role.SUMMARIZER, "\n\n".join(outputs.values()))

        elif self.l1_role == L1Role.VALIDATOR:
            return (
                "## Validation Report\n\n"
                f"### Correctness\n{outputs.get(L2Role.CORRECTNESS, '')}\n\n"
                f"### Completeness\n{outputs.get(L2Role.COMPLETENESS, '')}\n\n"
                f"### Quality Score\n{outputs.get(L2Role.SCORER, '')}"
            )

        elif self.l1_role == L1Role.EXECUTOR:
            return outputs.get(L2Role.ACTION_RUNNER, "\n\n".join(outputs.values()))

        else:
            return "\n\n---\n\n".join(
                f"### {role.value}\n{output}" for role, output in outputs.items()
            )
