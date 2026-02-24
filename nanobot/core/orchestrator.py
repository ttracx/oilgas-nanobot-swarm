"""
Queen Orchestrator v2 — full session lifecycle with Redis state.
Creates sessions, tracks progress, synthesizes with full history context.
"""

import asyncio
import json
import re
import uuid
import structlog

from nanobot.core.agent import AgentConfig, AgentRole, AgentTask
from nanobot.core.agent_v3 import NanobotV3, swarm_state
from nanobot.state.task_journal import TaskJournal
from nanobot.tools.base import ToolRegistry
from nanobot.core.agent_v2 import build_default_registry

log = structlog.get_logger()

SYSTEM_PROMPTS = {
    AgentRole.ORCHESTRATOR: """You are the Queen Orchestrator of a NeuralQuantum Nanobot Swarm.
Decompose complex goals into subtasks for specialized nanobots.

Respond with JSON:
{
  "plan_summary": "Brief approach description",
  "subtasks": [
    {
      "id": "task_1",
      "role": "researcher|coder|analyst|validator|executor",
      "instruction": "Specific instruction",
      "depends_on": [],
      "priority": 1
    }
  ],
  "synthesis_instruction": "How to combine results"
}

Minimize subtasks. Parallelize when possible. Be precise.""",

    AgentRole.RESEARCHER: """You are a Research Nanobot. Gather information, synthesize knowledge, provide accurate context.
Use web_search and http_fetch tools for current information. Be thorough and cite your reasoning.""",

    AgentRole.CODER: """You are a Code Nanobot. Write production-ready code with error handling, tests, and docs.
Use run_python to test your code before returning it. Default to Python with type hints.""",

    AgentRole.ANALYST: """You are an Analysis Nanobot. Deep reasoning, pattern recognition, decision analysis.
Think step by step. Show your reasoning chain explicitly.""",

    AgentRole.VALIDATOR: """You are a Validator Nanobot. Review outputs for correctness, completeness, quality.
Score quality 1-10. Use run_python to verify code claims. Be specific about issues.""",

    AgentRole.EXECUTOR: """You are an Executor Nanobot. Translate plans into concrete action steps.
Be sequential and specific. Use file_io to save outputs for persistence.""",
}


class NanobotSwarm:
    """Full swarm orchestrator with Redis session management."""

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000/v1",
        api_key: str = "nq-nanobot",
        max_parallel_agents: int = 8,
        tool_registry: ToolRegistry | None = None,
    ):
        self.vllm_url = vllm_url
        self.api_key = api_key
        self.max_parallel = max_parallel_agents
        self.semaphore = asyncio.Semaphore(max_parallel_agents)
        self.registry = tool_registry or build_default_registry()

    def _make_agent(self, role: AgentRole, session_id: str) -> NanobotV3:
        return NanobotV3(
            config=AgentConfig(
                role=role,
                name=f"{role.value}-{uuid.uuid4().hex[:6]}",
                system_prompt=SYSTEM_PROMPTS[role],
                max_tokens=2048,
                temperature=0.0 if role == AgentRole.ORCHESTRATOR else 0.1,
            ),
            session_id=session_id,
            vllm_base_url=self.vllm_url,
            api_key=self.api_key,
            tool_registry=self.registry,
        )

    def _parse_plan(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
            if match:
                return json.loads(match.group(1))
            raise ValueError(f"Could not parse plan: {text[:200]}")

    async def _run_subtask(
        self,
        task_def: dict,
        session_id: str,
        dep_results: dict[str, str],
    ) -> tuple[str, str]:
        async with self.semaphore:
            role = AgentRole(task_def["role"])
            agent = self._make_agent(role, session_id)
            await agent.initialize()

            task = AgentTask(
                id=task_def["id"],
                content=task_def["instruction"],
                context={"dep_results": dep_results} if dep_results else {},
                priority=task_def.get("priority", 5),
            )

            result = await agent.execute(task)
            await agent.shutdown()

            return (
                task_def["id"],
                result.output if result.success else f"FAILED: {result.error}",
            )

    async def run(self, goal: str, metadata: dict | None = None) -> dict:
        """Run full swarm session on a goal."""
        session_id = await swarm_state.create_session(goal, metadata)
        journal = TaskJournal(session_id)
        log.info("swarm_run_start", session_id=session_id, goal_preview=goal[:80])

        # Queen planning
        queen = self._make_agent(AgentRole.ORCHESTRATOR, session_id)
        await queen.initialize()

        session_history = await journal.get_full_context_for_orchestrator()
        plan_content = goal
        if session_history:
            plan_content = f"{session_history}\n\nNew Goal: {goal}"

        plan_task = AgentTask(
            id=str(uuid.uuid4()),
            content=f"Decompose this goal into a nanobot swarm execution plan:\n\n{plan_content}",
        )
        plan_result = await queen.execute(plan_task)
        await queen.shutdown()

        if not plan_result.success:
            await swarm_state.complete_session(session_id, "Planning failed", False)
            return {"success": False, "session_id": session_id, "error": plan_result.error}

        try:
            plan = self._parse_plan(plan_result.output)
        except ValueError as e:
            await swarm_state.complete_session(session_id, str(e), False)
            return {"success": False, "session_id": session_id, "error": str(e)}

        subtasks = plan.get("subtasks", [])
        await swarm_state.update_session(session_id, {"task_count": len(subtasks)})

        # Execute subtasks in dependency order
        completed: dict[str, str] = {}
        all_results: list[dict] = []

        def dep_level(t: dict) -> int:
            deps = t.get("depends_on", [])
            if not deps:
                return 0
            return max(
                dep_level(
                    next((s for s in subtasks if s["id"] == d), {"depends_on": []})
                )
                for d in deps
            ) + 1

        max_level = max((dep_level(t) for t in subtasks), default=0)

        for level in range(max_level + 1):
            level_tasks = [t for t in subtasks if dep_level(t) == level]
            log.info("executing_level", level=level, tasks=len(level_tasks))

            level_coros = [
                self._run_subtask(
                    t,
                    session_id,
                    {d: completed[d] for d in t.get("depends_on", []) if d in completed},
                )
                for t in level_tasks
            ]
            level_results = await asyncio.gather(*level_coros, return_exceptions=True)

            for task_def, res in zip(level_tasks, level_results):
                if isinstance(res, Exception):
                    tid, output = task_def["id"], f"Exception: {res}"
                else:
                    tid, output = res
                completed[tid] = output
                all_results.append({
                    "task_id": tid,
                    "role": task_def["role"],
                    "output": output,
                    "success": not output.startswith("FAILED:") and not output.startswith("Exception:"),
                })

            await swarm_state.update_session(
                session_id, {"completed_tasks": len(completed)}
            )

        # Synthesis — use dedicated synthesizer (not the planner prompt)
        from nanobot.core.agent_v3 import NanobotV3
        synth_agent = NanobotV3(
            config=AgentConfig(
                role=AgentRole.ORCHESTRATOR,
                name="synthesizer",
                system_prompt=(
                    "You are a Synthesis Agent. Combine the results from multiple specialist "
                    "agents into a single comprehensive answer. Do NOT output JSON. "
                    "Write a clear, well-structured text response."
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

        results_text = "\n\n".join([
            f"### {r['role'].upper()} ({r['task_id']}):\n{r['output'][:1500]}"
            for r in all_results
        ])
        synth_task = AgentTask(
            content=f"""Original Goal: {goal}

Subtask Results:
{results_text}

Synthesis Instruction: {plan.get('synthesis_instruction', 'Combine all results into a comprehensive final answer.')}

Produce the final comprehensive answer in plain text (NOT JSON):""",
        )
        synth_result = await synth_agent.execute(synth_task)
        await synth_agent.shutdown()

        final_answer = synth_result.output if synth_result.success else "Synthesis failed"

        await swarm_state.complete_session(session_id, final_answer, synth_result.success)
        summary = await journal.get_session_summary()

        log.info("swarm_complete", **{k: v for k, v in summary.items() if k != "session_id"}, session_id=session_id)

        return {
            "success": True,
            "session_id": session_id,
            "goal": goal,
            "plan_summary": plan.get("plan_summary"),
            "subtask_results": all_results,
            "final_answer": final_answer,
            "session_summary": summary,
        }
