"""
Per-agent persistent memory.
Each nanobot has:
  - Short-term: recent conversation turns (sliding window)
  - Long-term: extracted facts, decisions, learned patterns
  - Episodic: summaries of completed task sessions
"""

import json
import time
from typing import Any
from nanobot.state.connection import get_redis, NS
import structlog

log = structlog.get_logger()

SHORT_TERM_TTL = 60 * 60 * 4
LONG_TERM_TTL = 60 * 60 * 24 * 30
EPISODIC_TTL = 60 * 60 * 24 * 7

SHORT_TERM_MAX_TURNS = 50
LONG_TERM_MAX_FACTS = 200


class AgentMemoryStore:
    """Persistent memory for a single nanobot agent."""

    def __init__(self, agent_id: str, role: str):
        self.agent_id = agent_id
        self.role = role
        self._key = lambda t: f"{NS['agent_memory']}{agent_id}:{t}"

    async def push_conversation_turn(self, role: str, content: str) -> None:
        redis = await get_redis()
        key = self._key("conversation")
        turn = json.dumps({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        pipe = redis.pipeline()
        pipe.rpush(key, turn)
        pipe.ltrim(key, -SHORT_TERM_MAX_TURNS, -1)
        pipe.expire(key, SHORT_TERM_TTL)
        await pipe.execute()

    async def get_conversation_history(self, last_n: int = 20) -> list[dict]:
        redis = await get_redis()
        key = self._key("conversation")
        raw_turns = await redis.lrange(key, -last_n, -1)
        turns = []
        for raw in raw_turns:
            try:
                turn = json.loads(raw)
                turns.append({"role": turn["role"], "content": turn["content"]})
            except json.JSONDecodeError:
                continue
        return turns

    async def clear_conversation(self) -> None:
        redis = await get_redis()
        await redis.delete(self._key("conversation"))

    async def store_fact(self, fact_key: str, value: Any, ttl: int = LONG_TERM_TTL) -> None:
        redis = await get_redis()
        key = self._key(f"fact:{fact_key}")
        await redis.setex(
            key,
            ttl,
            json.dumps({"value": value, "stored_at": time.time(), "agent": self.agent_id}),
        )
        await redis.sadd(self._key("fact_index"), fact_key)
        await redis.expire(self._key("fact_index"), LONG_TERM_TTL)

    async def get_fact(self, fact_key: str) -> Any | None:
        redis = await get_redis()
        raw = await redis.get(self._key(f"fact:{fact_key}"))
        if raw is None:
            return None
        data = json.loads(raw)
        return data.get("value")

    async def get_all_facts(self) -> dict[str, Any]:
        redis = await get_redis()
        fact_keys = await redis.smembers(self._key("fact_index"))
        facts = {}
        for fk in fact_keys:
            val = await self.get_fact(fk)
            if val is not None:
                facts[fk] = val
        return facts

    async def delete_fact(self, fact_key: str) -> None:
        redis = await get_redis()
        await redis.delete(self._key(f"fact:{fact_key}"))
        await redis.srem(self._key("fact_index"), fact_key)

    async def store_episode(
        self,
        session_id: str,
        goal: str,
        outcome: str,
        key_decisions: list[str],
        success: bool,
    ) -> None:
        redis = await get_redis()
        key = self._key(f"episode:{session_id}")
        episode = {
            "session_id": session_id,
            "goal": goal,
            "outcome": outcome,
            "key_decisions": key_decisions,
            "success": success,
            "agent_id": self.agent_id,
            "role": self.role,
            "timestamp": time.time(),
        }
        await redis.setex(key, EPISODIC_TTL, json.dumps(episode))
        await redis.lpush(self._key("episode_index"), session_id)
        await redis.ltrim(self._key("episode_index"), 0, 99)
        await redis.expire(self._key("episode_index"), EPISODIC_TTL)
        log.info("episode_stored", agent_id=self.agent_id, session=session_id)

    async def get_recent_episodes(self, n: int = 5) -> list[dict]:
        redis = await get_redis()
        session_ids = await redis.lrange(self._key("episode_index"), 0, n - 1)
        episodes = []
        for sid in session_ids:
            raw = await redis.get(self._key(f"episode:{sid}"))
            if raw:
                episodes.append(json.loads(raw))
        return episodes

    async def build_memory_context(self) -> str:
        parts = []

        episodes = await self.get_recent_episodes(3)
        if episodes:
            ep_lines = [
                f"- [{e['timestamp']:.0f}] Goal: {e['goal'][:80]} -> "
                f"{'OK' if e['success'] else 'FAIL'} {e['outcome'][:80]}"
                for e in episodes
            ]
            parts.append("RECENT TASK HISTORY:\n" + "\n".join(ep_lines))

        facts = await self.get_all_facts()
        if facts:
            fact_lines = [f"- {k}: {str(v)[:100]}" for k, v in list(facts.items())[:10]]
            parts.append("KNOWN FACTS:\n" + "\n".join(fact_lines))

        if not parts:
            return ""

        return "=== AGENT MEMORY ===\n" + "\n\n".join(parts) + "\n=== END MEMORY ===\n\n"
