"""
HierarchicalSwarm — the full 3-tier orchestrator.
Queen (L0) -> L1 Domain Leads -> L2 Sub-agents
Main entry point for the entire nanobot system.
"""

import asyncio
import json
import re
import uuid
import structlog
from typing import Any

from nanobot.core.roles import L1Role
from nanobot.core.l1_agent import L1Agent
from nanobot.core.agent import AgentConfig, AgentRole, AgentTask, AgentResult
from nanobot.core.agent_v3 import NanobotV3, swarm_state
from nanobot.state.task_journal import TaskJournal
from nanobot.tools.base import ToolRegistry
from nanobot.core.agent_v2 import build_default_registry

log = structlog.get_logger()

QUEEN_PROMPT = """You are the Queen Orchestrator of the NeuralQuantum Hierarchical Nanobot Swarm.

You command L1 Domain Lead agents, each of which commands their own sub-swarm:
- coder      -> Code Planner -> Code Writer -> Code Tester -> Code Reviewer
- researcher -> Web Searcher -> Synthesizer -> Fact Verifier
- analyst    -> Reasoner -> Critiquer -> Summarizer
- validator  -> Correctness + Completeness -> Scorer
- executor   -> Action Planner -> Action Runner
- architect  -> Solo system design specialist

Decompose the goal into L1-level tasks. Each task will be fully handled by the L1 agent's sub-swarm.
Design tasks at L1 granularity — do NOT try to specify L2 details.

Respond with JSON:
{
  "plan_summary": "High-level approach",
  "l1_tasks": [
    {
      "id": "t1",
      "l1_role": "coder|researcher|analyst|validator|executor|architect",
      "instruction": "What the L1 lead should accomplish (1-2 sentences)",
      "depends_on": [],
      "priority": 1
    }
  ],
  "synthesis_instruction": "How to combine L1 outputs into final answer"
}"""


class HierarchicalSwarm:
    """3-tier swarm: Queen -> L1 Leads -> L2 Sub-agents."""

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000/v1",
        api_key: str = "nq-nanobot",
        max_concurrent_l1: int = 3,
        max_concurrent_global: int = 12,
        tool_registry: ToolRegistry | None = None,
    ):
        self.vllm_url = vllm_url
        self.api_key = api_key
        self.registry = tool_registry or build_default_registry()
        self.l1_semaphore = asyncio.Semaphore(max_concurrent_l1)
        self.global_semaphore = asyncio.Semaphore(max_concurrent_global)
        self.max_concurrent_l1 = max_concurrent_l1
        self.max_concurrent_global = max_concurrent_global

    def _make_queen(self, session_id: str) -> NanobotV3:
        return NanobotV3(
            config=AgentConfig(
                role=AgentRole.ORCHESTRATOR,
                name="queen",
                system_prompt=QUEEN_PROMPT,
                max_tokens=2048,
                temperature=0.0,
            ),
            session_id=session_id,
            vllm_base_url=self.vllm_url,
            api_key=self.api_key,
            tool_registry=self.registry,
        )

    def _make_l1(self, role: L1Role, session_id: str) -> L1Agent:
        return L1Agent(
            role=role,
            session_id=session_id,
            vllm_url=self.vllm_url,
            api_key=self.api_key,
            tool_registry=self.registry,
            global_semaphore=self.global_semaphore,
        )

    def _parse_plan(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
            if m:
                return json.loads(m.group(1))
            raise ValueError(f"Could not parse plan: {text[:200]}")

    def _dep_level(self, task_id: str, tasks: list[dict]) -> int:
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task or not task.get("depends_on"):
            return 0
        return max(self._dep_level(d, tasks) for d in task["depends_on"]) + 1

    async def _run_l1_task(
        self,
        task_def: dict,
        session_id: str,
        dep_outputs: dict[str, str],
    ) -> tuple[str, AgentResult]:
        async with self.l1_semaphore:
            role = L1Role(task_def["l1_role"])
            agent = self._make_l1(role, session_id)
            await agent.initialize()

            instruction = task_def["instruction"]
            if dep_outputs:
                dep_text = "\n\n".join([
                    f"[{tid}]: {output[:800]}"
                    for tid, output in dep_outputs.items()
                ])
                instruction = f"{instruction}\n\n## Context from prior tasks:\n{dep_text}"

            task = AgentTask(
                id=task_def["id"],
                content=instruction,
                priority=task_def.get("priority", 5),
            )

            result = await agent.execute(task)
            await agent.shutdown()
            return task_def["id"], result

    async def run(self, goal: str, metadata: dict | None = None) -> dict[str, Any]:
        """Execute the full 3-tier hierarchical swarm on a goal."""
        session_id = await swarm_state.create_session(goal, metadata)
        journal = TaskJournal(session_id)
        log.info("hierarchical_swarm_start", session_id=session_id)

        # Queen planning
        queen = self._make_queen(session_id)
        await queen.initialize()

        history_ctx = await journal.get_full_context_for_orchestrator()
        plan_input = f"{history_ctx}\n\nGoal: {goal}" if history_ctx else f"Goal: {goal}"

        plan_task = AgentTask(id=str(uuid.uuid4()), content=plan_input)
        plan_result = await queen.execute(plan_task)
        await queen.shutdown()

        if not plan_result.success:
            await swarm_state.complete_session(session_id, "Queen planning failed", False)
            return {"success": False, "session_id": session_id, "error": plan_result.error}

        try:
            plan = self._parse_plan(plan_result.output)
        except ValueError as e:
            await swarm_state.complete_session(session_id, str(e), False)
            return {"success": False, "session_id": session_id, "error": str(e)}

        l1_tasks = plan.get("l1_tasks", [])
        log.info("queen_plan_ready", l1_task_count=len(l1_tasks))
        await swarm_state.update_session(session_id, {"task_count": len(l1_tasks)})

        # Execute L1 tasks in dependency order
        completed_outputs: dict[str, str] = {}
        all_l1_results: list[dict] = []

        max_level = max(
            (self._dep_level(t["id"], l1_tasks) for t in l1_tasks), default=0
        )

        for level in range(max_level + 1):
            level_tasks = [
                t
                for t in l1_tasks
                if self._dep_level(t["id"], l1_tasks) == level
            ]

            log.info(
                "l1_level_executing",
                level=level,
                roles=[t["l1_role"] for t in level_tasks],
            )

            coros = [
                self._run_l1_task(
                    t,
                    session_id,
                    {
                        d: completed_outputs[d]
                        for d in t.get("depends_on", [])
                        if d in completed_outputs
                    },
                )
                for t in level_tasks
            ]
            level_results = await asyncio.gather(*coros, return_exceptions=True)

            for task_def, res in zip(level_tasks, level_results):
                if isinstance(res, Exception):
                    tid = task_def["id"]
                    output = f"FAILED: {res}"
                    success = False
                else:
                    tid, agent_result = res
                    output = agent_result.output
                    success = agent_result.success

                completed_outputs[tid] = output
                all_l1_results.append({
                    "task_id": tid,
                    "l1_role": task_def["l1_role"],
                    "instruction": task_def["instruction"],
                    "output": output,
                    "success": success,
                })

            await swarm_state.update_session(
                session_id, {"completed_tasks": len(completed_outputs)}
            )

        # Queen synthesis — use a dedicated synthesizer prompt (not the planner prompt)
        synth_agent = NanobotV3(
            config=AgentConfig(
                role=AgentRole.ORCHESTRATOR,
                name="queen-synthesizer",
                system_prompt=(
                    "You are the Queen Synthesizer of the NeuralQuantum Nanobot Swarm. "
                    "Your job is to combine results from multiple domain lead agents into "
                    "a single comprehensive answer. Do NOT output JSON. Write a clear, "
                    "well-structured text response that directly answers the original goal."
                ),
                max_tokens=4096,
                temperature=0.1,
            ),
            session_id=session_id,
            vllm_base_url=self.vllm_url,
            api_key=self.api_key,
            tool_registry=self.registry,
        )
        await synth_agent.initialize()

        # Truncate individual results to avoid context overflow
        results_text = "\n\n".join([
            f"### {r['l1_role'].upper()} ({r['task_id']}):\n{r['output'][:1500]}"
            for r in all_l1_results
            if r["success"]
        ])

        synth_instruction = plan.get(
            "synthesis_instruction", "Combine all results into a comprehensive answer."
        )

        synth_task = AgentTask(
            content=(
                f"Original Goal: {goal}\n\n"
                f"L1 Domain Lead Results:\n{results_text}\n\n"
                f"Synthesis Instruction: {synth_instruction}\n\n"
                f"Produce the final comprehensive answer in plain text (NOT JSON):"
            ),
        )
        synth_result = await synth_agent.execute(synth_task)
        await synth_agent.shutdown()

        final_answer = synth_result.output if synth_result.success else "Synthesis failed"

        await swarm_state.complete_session(session_id, final_answer, synth_result.success)
        summary = await journal.get_session_summary()

        log.info(
            "hierarchical_swarm_complete",
            session_id=session_id,
            l1_tasks=len(all_l1_results),
            success=synth_result.success,
        )

        return {
            "success": True,
            "session_id": session_id,
            "goal": goal,
            "plan_summary": plan.get("plan_summary"),
            "l1_results": all_l1_results,
            "final_answer": final_answer,
            "session_summary": summary,
        }
