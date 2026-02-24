"""
Global swarm state management.
Tracks active sessions, agent registry, queue depths, and health.
"""

import json
import time
import uuid
from nanobot.state.connection import get_redis, NS
import structlog

log = structlog.get_logger()

SESSION_TTL = 60 * 60 * 24
AGENT_TTL = 60 * 60 * 2
HEARTBEAT_IV = 30


class SwarmStateManager:
    """Centralized swarm state — shared across all agents."""

    async def create_session(self, goal: str, metadata: dict | None = None) -> str:
        redis = await get_redis()
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "goal": goal,
            "metadata": metadata or {},
            "status": "active",
            "created_at": time.time(),
            "updated_at": time.time(),
            "agent_count": 0,
            "task_count": 0,
            "completed_tasks": 0,
        }
        key = f"{NS['session']}{session_id}"
        await redis.setex(key, SESSION_TTL, json.dumps(session))
        await redis.lpush(f"{NS['swarm_state']}sessions", session_id)
        await redis.ltrim(f"{NS['swarm_state']}sessions", 0, 999)

        log.info("session_created", session_id=session_id, goal_preview=goal[:80])
        return session_id

    async def update_session(self, session_id: str, updates: dict) -> None:
        redis = await get_redis()
        key = f"{NS['session']}{session_id}"
        raw = await redis.get(key)
        if not raw:
            log.warning("session_not_found", session_id=session_id)
            return
        session = json.loads(raw)
        session.update(updates)
        session["updated_at"] = time.time()
        await redis.setex(key, SESSION_TTL, json.dumps(session))

    async def complete_session(
        self,
        session_id: str,
        final_answer: str,
        success: bool,
    ) -> None:
        await self.update_session(session_id, {
            "status": "complete" if success else "failed",
            "final_answer": final_answer,
            "completed_at": time.time(),
            "success": success,
        })

    async def get_session(self, session_id: str) -> dict | None:
        redis = await get_redis()
        raw = await redis.get(f"{NS['session']}{session_id}")
        return json.loads(raw) if raw else None

    async def list_recent_sessions(self, n: int = 10) -> list[dict]:
        redis = await get_redis()
        session_ids = await redis.lrange(f"{NS['swarm_state']}sessions", 0, n - 1)
        sessions = []
        for sid in session_ids:
            s = await self.get_session(sid)
            if s:
                sessions.append(s)
        return sessions

    async def register_agent(
        self,
        agent_id: str,
        role: str,
        name: str,
        session_id: str,
    ) -> None:
        redis = await get_redis()
        agent_rec = {
            "agent_id": agent_id,
            "role": role,
            "name": name,
            "session_id": session_id,
            "status": "idle",
            "registered_at": time.time(),
            "last_heartbeat": time.time(),
            "tasks_completed": 0,
            "tokens_used": 0,
        }
        key = f"{NS['swarm_state']}agent:{agent_id}"
        await redis.setex(key, AGENT_TTL, json.dumps(agent_rec))
        await redis.sadd(f"{NS['swarm_state']}active_agents", agent_id)

    async def update_agent_status(
        self,
        agent_id: str,
        status: str,
        tokens_delta: int = 0,
    ) -> None:
        redis = await get_redis()
        key = f"{NS['swarm_state']}agent:{agent_id}"
        raw = await redis.get(key)
        if not raw:
            return
        agent = json.loads(raw)
        agent["status"] = status
        agent["last_heartbeat"] = time.time()
        agent["tokens_used"] = agent.get("tokens_used", 0) + tokens_delta
        if status == "done":
            agent["tasks_completed"] = agent.get("tasks_completed", 0) + 1
        await redis.setex(key, AGENT_TTL, json.dumps(agent))

    async def deregister_agent(self, agent_id: str) -> None:
        redis = await get_redis()
        await redis.srem(f"{NS['swarm_state']}active_agents", agent_id)
        await redis.delete(f"{NS['swarm_state']}agent:{agent_id}")

    async def get_active_agents(self) -> list[dict]:
        redis = await get_redis()
        agent_ids = await redis.smembers(f"{NS['swarm_state']}active_agents")
        agents = []
        for aid in agent_ids:
            raw = await redis.get(f"{NS['swarm_state']}agent:{aid}")
            if raw:
                agents.append(json.loads(raw))
        return agents

    async def get_swarm_health(self) -> dict:
        redis = await get_redis()
        agents = await self.get_active_agents()
        sessions = await self.list_recent_sessions(5)
        failed_queue = await redis.llen(f"{NS['queue']}failed")
        info = await redis.info("memory")
        used_mb = info.get("used_memory", 0) / 1024 / 1024
        peak_mb = info.get("used_memory_peak", 0) / 1024 / 1024

        role_counts: dict[str, int] = {}
        for a in agents:
            r = a.get("role", "unknown")
            role_counts[r] = role_counts.get(r, 0) + 1

        return {
            "timestamp": time.time(),
            "active_agents": len(agents),
            "agent_breakdown": role_counts,
            "recent_sessions": len(sessions),
            "failed_queue_depth": failed_queue,
            "redis_memory_used_mb": round(used_mb, 1),
            "redis_memory_peak_mb": round(peak_mb, 1),
            "agents": agents,
        }

    async def acquire_lock(self, resource: str, ttl: int = 30) -> str | None:
        redis = await get_redis()
        lock_key = f"{NS['swarm_state']}lock:{resource}"
        token = str(uuid.uuid4())
        acquired = await redis.set(lock_key, token, nx=True, ex=ttl)
        return token if acquired else None

    async def release_lock(self, resource: str, token: str) -> bool:
        redis = await get_redis()
        lock_key = f"{NS['swarm_state']}lock:{resource}"
        current = await redis.get(lock_key)
        if current == token:
            await redis.delete(lock_key)
            return True
        return False
