"""
Append-only task journal for all swarm activity.
Provides full audit trail, replay buffer, and cross-session analytics.
"""

import json
import time
from enum import Enum
from nanobot.state.connection import get_redis, NS
import structlog

log = structlog.get_logger()

JOURNAL_TTL = 60 * 60 * 24 * 14
MAX_TASKS = 10_000


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    RETRYING = "retrying"


class TaskJournal:
    """Central journal for all task activity in the swarm."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._skey = f"{NS['task_history']}session:{session_id}"

    async def record_task_start(
        self,
        task_id: str,
        agent_id: str,
        agent_role: str,
        content: str,
        parent_task_id: str | None = None,
    ) -> None:
        redis = await get_redis()
        record = {
            "task_id": task_id,
            "agent_id": agent_id,
            "agent_role": agent_role,
            "content_preview": content[:200],
            "parent_task_id": parent_task_id,
            "status": TaskStatus.RUNNING,
            "started_at": time.time(),
            "session_id": self.session_id,
        }
        pipe = redis.pipeline()
        pipe.setex(
            f"{NS['task_history']}{task_id}",
            JOURNAL_TTL,
            json.dumps(record),
        )
        pipe.lpush(self._skey, task_id)
        pipe.ltrim(self._skey, 0, MAX_TASKS - 1)
        pipe.expire(self._skey, JOURNAL_TTL)
        await pipe.execute()

    async def record_task_complete(
        self,
        task_id: str,
        output: str,
        success: bool,
        tokens_used: int = 0,
        duration_seconds: float = 0.0,
        tool_calls: list[str] | None = None,
    ) -> None:
        redis = await get_redis()
        key = f"{NS['task_history']}{task_id}"
        raw = await redis.get(key)
        if raw:
            record = json.loads(raw)
        else:
            record = {"task_id": task_id}

        record.update({
            "status": TaskStatus.COMPLETE if success else TaskStatus.FAILED,
            "output_preview": output[:500],
            "output_full": output,
            "success": success,
            "tokens_used": tokens_used,
            "duration_seconds": duration_seconds,
            "tool_calls": tool_calls or [],
            "completed_at": time.time(),
        })
        await redis.setex(key, JOURNAL_TTL, json.dumps(record))

        if not success:
            await redis.lpush(
                f"{NS['queue']}failed",
                json.dumps({"task_id": task_id, "session_id": self.session_id}),
            )

    async def get_task(self, task_id: str) -> dict | None:
        redis = await get_redis()
        raw = await redis.get(f"{NS['task_history']}{task_id}")
        return json.loads(raw) if raw else None

    async def get_session_tasks(self, limit: int = 50) -> list[dict]:
        redis = await get_redis()
        task_ids = await redis.lrange(self._skey, 0, limit - 1)
        tasks = []
        for tid in task_ids:
            raw = await redis.get(f"{NS['task_history']}{tid}")
            if raw:
                tasks.append(json.loads(raw))
        return tasks

    async def get_session_summary(self) -> dict:
        tasks = await self.get_session_tasks(limit=1000)
        total = len(tasks)
        successful = sum(1 for t in tasks if t.get("success"))
        total_tok = sum(t.get("tokens_used", 0) for t in tasks)
        avg_dur = (
            sum(t.get("duration_seconds", 0) for t in tasks) / total if total else 0
        )
        roles_used = list({t.get("agent_role", "unknown") for t in tasks})

        return {
            "session_id": self.session_id,
            "total_tasks": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": round(successful / total * 100, 1) if total else 0,
            "total_tokens": total_tok,
            "avg_duration_seconds": round(avg_dur, 2),
            "roles_used": roles_used,
        }

    async def get_full_context_for_orchestrator(self, max_tasks: int = 10) -> str:
        tasks = await self.get_session_tasks(limit=max_tasks)
        if not tasks:
            return ""

        lines = ["=== SESSION TASK HISTORY ==="]
        for t in tasks:
            status_icon = "OK" if t.get("success") else "FAIL"
            lines.append(
                f"[{status_icon}] [{t.get('agent_role', '?')}] "
                f"{t.get('content_preview', '')[:80]}"
                f" -> {t.get('output_preview', '')[:80]}"
            )
        lines.append("=== END HISTORY ===")
        return "\n".join(lines)
