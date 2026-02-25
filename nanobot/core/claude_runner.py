"""
ClaudeTeamRunner — runs agent teams using the Anthropic Claude API.

Provides a swarm-compatible runner interface for the scheduler.
Supports both "flat" (single Claude agent with tools) and simple
multi-step execution for agent teams.
"""

import os
import uuid
import structlog
from typing import Any

from anthropic import AsyncAnthropic

from nanobot.core.agent import AgentConfig, AgentRole, AgentTask
from nanobot.core.agent_claude import NanobotClaude
from nanobot.tools.base import ToolRegistry
from nanobot.core.agent_v2 import build_default_registry
from nanobot.state.swarm_state import SwarmStateManager
from nanobot.state.task_journal import TaskJournal

log = structlog.get_logger()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

swarm_state = SwarmStateManager()


class ClaudeTeamRunner:
    """
    Runs agent teams through Claude's native tool-use API.

    For "flat" teams: single NanobotClaude with full tool access.
    For "hierarchical" teams: Claude plans subtasks, then executes each
    with a dedicated NanobotClaude (simplified 2-tier).
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        anthropic_client: AsyncAnthropic | None = None,
    ):
        self.registry = tool_registry or build_default_registry()
        self.client = anthropic_client or AsyncAnthropic(
            api_key=ANTHROPIC_API_KEY,
            timeout=600.0,
            max_retries=0,
        )

    async def run(self, goal: str, mode: str = "flat", context: dict | None = None) -> dict[str, Any]:
        """
        Execute a goal using Claude. Compatible with the scheduler's _swarm_runner interface.

        Returns the standard swarm result dict:
        {
            "success": bool,
            "session_id": str,
            "goal": str,
            "final_answer": str,
            "subtask_results": [...],
            "session_summary": {...},
        }
        """
        session_id = await swarm_state.create_session(goal, context)
        journal = TaskJournal(session_id)

        log.info("claude_team_run_start", session_id=session_id, mode=mode)

        try:
            if mode == "hierarchical":
                result = await self._run_hierarchical(goal, session_id, context or {})
            else:
                result = await self._run_flat(goal, session_id, context or {})

            await swarm_state.complete_session(
                session_id, result.get("final_answer", ""), result.get("success", False)
            )
            summary = await journal.get_session_summary()
            result["session_summary"] = summary
            return result

        except Exception as e:
            log.error("claude_team_run_failed", session_id=session_id, error=str(e))
            await swarm_state.complete_session(session_id, str(e), False)
            return {
                "success": False,
                "session_id": session_id,
                "goal": goal,
                "final_answer": "",
                "error": str(e),
                "subtask_results": [],
            }

    async def _run_flat(self, goal: str, session_id: str, context: dict) -> dict:
        """Single Claude agent with full tool access."""
        agent = NanobotClaude(
            config=AgentConfig(
                role=AgentRole.EXECUTOR,
                name="claude-team-agent",
                system_prompt="",  # System prompt comes from the goal (injected by scheduler)
                max_tokens=4096,
                temperature=0.1,
            ),
            session_id=session_id,
            tool_registry=self.registry,
            anthropic_client=self.client,
        )
        await agent.initialize()

        task = AgentTask(
            id=str(uuid.uuid4()),
            content=goal,
            context=context,
        )

        result = await agent.execute(task)
        await agent.shutdown()

        return {
            "success": result.success,
            "session_id": session_id,
            "goal": goal,
            "final_answer": result.output,
            "subtask_results": [{
                "task_id": result.task_id,
                "role": "executor",
                "output": result.output,
                "success": result.success,
                "tokens": result.tokens_used,
                "duration": result.duration_seconds,
            }],
        }

    async def _run_hierarchical(self, goal: str, session_id: str, context: dict) -> dict:
        """
        Two-phase Claude execution:
        1. Planner: Claude breaks goal into steps
        2. Executor: Claude executes each step with tools
        """
        # Phase 1: Plan
        planner = NanobotClaude(
            config=AgentConfig(
                role=AgentRole.ORCHESTRATOR,
                name="claude-planner",
                system_prompt=(
                    "You are a task planner. Break the given goal into 2-5 concrete steps. "
                    "Each step should be a clear, actionable instruction. "
                    "Respond with a JSON array of steps:\n"
                    '[{"id": "s1", "instruction": "..."}, ...]'
                ),
                max_tokens=2048,
                temperature=0.0,
            ),
            session_id=session_id,
            tool_registry=self.registry,
            anthropic_client=self.client,
        )
        await planner.initialize()

        plan_task = AgentTask(content=goal, context=context)
        plan_result = await planner.execute(plan_task)
        await planner.shutdown()

        if not plan_result.success:
            return {
                "success": False,
                "session_id": session_id,
                "goal": goal,
                "final_answer": "",
                "error": f"Planning failed: {plan_result.error}",
                "subtask_results": [],
            }

        # Parse plan
        import json
        import re
        try:
            steps = json.loads(plan_result.output)
        except json.JSONDecodeError:
            m = re.search(r"\[[\s\S]+\]", plan_result.output)
            if m:
                steps = json.loads(m.group(0))
            else:
                # Fallback: treat entire goal as single step
                steps = [{"id": "s1", "instruction": goal}]

        # Phase 2: Execute each step
        subtask_results = []
        accumulated_context = ""

        for step in steps:
            instruction = step.get("instruction", str(step))
            step_id = step.get("id", f"s{len(subtask_results)+1}")

            executor = NanobotClaude(
                config=AgentConfig(
                    role=AgentRole.EXECUTOR,
                    name=f"claude-executor-{step_id}",
                    system_prompt="",
                    max_tokens=4096,
                    temperature=0.1,
                ),
                session_id=session_id,
                tool_registry=self.registry,
                anthropic_client=self.client,
            )
            await executor.initialize()

            step_content = instruction
            if accumulated_context:
                step_content = f"Previous context:\n{accumulated_context[:2000]}\n\nCurrent step:\n{instruction}"

            step_task = AgentTask(id=step_id, content=step_content, context=context)
            step_result = await executor.execute(step_task)
            await executor.shutdown()

            subtask_results.append({
                "task_id": step_id,
                "instruction": instruction,
                "output": step_result.output,
                "success": step_result.success,
                "tokens": step_result.tokens_used,
                "duration": step_result.duration_seconds,
            })

            if step_result.success:
                accumulated_context += f"\n[{step_id}]: {step_result.output[:500]}"

        # Synthesize
        all_success = all(r["success"] for r in subtask_results)
        results_text = "\n\n".join(
            f"### Step {r['task_id']}:\n{r['output'][:1000]}"
            for r in subtask_results
            if r["success"]
        )

        synthesizer = NanobotClaude(
            config=AgentConfig(
                role=AgentRole.ORCHESTRATOR,
                name="claude-synthesizer",
                system_prompt=(
                    "Combine the step results into a single comprehensive answer. "
                    "Write clear text, not JSON. Be concise but thorough."
                ),
                max_tokens=4096,
                temperature=0.1,
            ),
            session_id=session_id,
            tool_registry=self.registry,
            anthropic_client=self.client,
        )
        await synthesizer.initialize()

        synth_task = AgentTask(
            content=f"Original goal: {goal}\n\nStep results:\n{results_text}\n\nSynthesize a final answer:",
        )
        synth_result = await synthesizer.execute(synth_task)
        await synthesizer.shutdown()

        return {
            "success": synth_result.success and all_success,
            "session_id": session_id,
            "goal": goal,
            "plan_summary": plan_result.output[:200],
            "final_answer": synth_result.output if synth_result.success else results_text,
            "subtask_results": subtask_results,
        }
