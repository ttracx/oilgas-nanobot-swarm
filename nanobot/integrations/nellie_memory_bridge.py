"""
Nellie Memory Bridge — Persistent memory sync between NellieNano and the Nanobot Swarm.

Bridges two memory systems:
1. NellieNano's file-based MemoryStore (MEMORY.md + HISTORY.md)
2. Nanobot Swarm's Redis-backed state (sessions, task journals, agent results)

Provides:
- Auto-persist swarm results to NellieNano's HISTORY.md
- Load NellieNano's MEMORY.md into swarm context for preflight
- Workspace sync: share files between Nellie workspace and swarm output
- Session continuity: resume swarm sessions across NellieNano restarts
"""

import asyncio
import json
import time
from pathlib import Path
from datetime import datetime

import structlog

from nanobot.state.connection import get_redis, NS

log = structlog.get_logger()

# NellieNano workspace paths
NELLIE_WORKSPACE = Path.home() / ".nellienano" / "workspace"
NELLIE_MEMORY_DIR = NELLIE_WORKSPACE / "memory"
NELLIE_MEMORY_FILE = NELLIE_MEMORY_DIR / "MEMORY.md"
NELLIE_HISTORY_FILE = NELLIE_MEMORY_DIR / "HISTORY.md"

# Redis namespace for bridge state
BRIDGE_NS = f"{NS.get('swarm_state', 'nq:swarm:')}bridge:"

# Sync interval and retention
SYNC_INTERVAL_SECONDS = 60
MAX_HISTORY_ENTRIES = 500


class NellieMemoryBridge:
    """Bidirectional memory bridge between NellieNano and Nanobot Swarm."""

    def __init__(self):
        self._last_sync_cursor: str = ""
        self._running = False

    async def initialize(self) -> None:
        """Set up bridge directories and load sync cursor from Redis."""
        NELLIE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

        redis = await get_redis()
        cursor = await redis.get(f"{BRIDGE_NS}sync_cursor")
        if cursor:
            self._last_sync_cursor = cursor
        log.info("nellie_bridge_init", cursor=self._last_sync_cursor)

    async def persist_swarm_result(self, session_id: str, result: dict) -> None:
        """Write a swarm session result to NellieNano's HISTORY.md and Redis."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        goal = result.get("goal", "Unknown goal")
        final_answer = result.get("final_answer", "No answer")
        plan_summary = result.get("plan_summary", "")
        summary = result.get("session_summary", {})

        # Build history entry
        entry_lines = [
            f"## Swarm Session: {session_id[:12]}",
            f"**Time:** {timestamp}",
            f"**Goal:** {goal}",
        ]
        if plan_summary:
            entry_lines.append(f"**Plan:** {plan_summary}")
        entry_lines.extend([
            f"**Tasks:** {summary.get('total_tasks', 0)} "
            f"(Success: {summary.get('successful', 0)}, "
            f"Failed: {summary.get('failed', 0)})",
            f"**Tokens:** {summary.get('total_tokens', 0)}",
            f"**Success Rate:** {summary.get('success_rate', 0)}%",
            "",
            "### Result",
            final_answer[:2000],
            "",
            "---",
            "",
        ])
        entry = "\n".join(entry_lines)

        # Append to HISTORY.md
        NELLIE_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(NELLIE_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(entry)

        # Also store in Redis for cross-session access
        redis = await get_redis()
        bridge_record = {
            "session_id": session_id,
            "goal": goal[:500],
            "final_answer": final_answer[:2000],
            "plan_summary": plan_summary,
            "success_rate": summary.get("success_rate", 0),
            "total_tasks": summary.get("total_tasks", 0),
            "total_tokens": summary.get("total_tokens", 0),
            "persisted_at": time.time(),
        }
        key = f"{BRIDGE_NS}result:{session_id}"
        await redis.setex(key, 60 * 60 * 24 * 7, json.dumps(bridge_record))  # 7 day TTL

        # Add to session index
        await redis.lpush(f"{BRIDGE_NS}results_index", session_id)
        await redis.ltrim(f"{BRIDGE_NS}results_index", 0, MAX_HISTORY_ENTRIES - 1)

        log.info("nellie_result_persisted", session_id=session_id[:12], goal=goal[:60])

    async def load_nellie_context(self) -> str:
        """Load NellieNano's long-term memory for swarm preflight context."""
        if not NELLIE_MEMORY_FILE.exists():
            return ""

        content = NELLIE_MEMORY_FILE.read_text(encoding="utf-8").strip()
        if not content:
            return ""

        return f"## Nellie's Long-Term Memory\n{content}"

    async def get_recent_swarm_history(self, n: int = 10) -> list[dict]:
        """Get recent swarm results from Redis bridge store."""
        redis = await get_redis()
        session_ids = await redis.lrange(f"{BRIDGE_NS}results_index", 0, n - 1)
        results = []
        for sid in session_ids:
            raw = await redis.get(f"{BRIDGE_NS}result:{sid}")
            if raw:
                results.append(json.loads(raw))
        return results

    async def sync_workspace(self, session_id: str, artifacts: dict[str, str]) -> None:
        """Sync swarm output artifacts to NellieNano's workspace directory."""
        swarm_output_dir = NELLIE_WORKSPACE / "swarm_output" / session_id[:12]
        swarm_output_dir.mkdir(parents=True, exist_ok=True)

        for filename, content in artifacts.items():
            filepath = swarm_output_dir / filename
            filepath.write_text(content, encoding="utf-8")
            log.info("workspace_synced", file=str(filepath))

        # Write manifest
        manifest = {
            "session_id": session_id,
            "synced_at": datetime.now().isoformat(),
            "files": list(artifacts.keys()),
        }
        (swarm_output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

    async def update_sync_cursor(self, cursor: str) -> None:
        """Update the sync cursor in Redis."""
        redis = await get_redis()
        await redis.set(f"{BRIDGE_NS}sync_cursor", cursor)
        self._last_sync_cursor = cursor

    async def sync_vault_entry(self, category: str, name: str, content: str) -> None:
        """Sync a vault entity to Redis for fast cross-session retrieval.

        Stores entity metadata in a Redis hash and adds to a searchable index.
        This allows memory_search to find vault entities without hitting disk.
        """
        redis = await get_redis()
        key = f"{BRIDGE_NS}vault:{category}:{name}"
        await redis.hset(key, mapping={
            "category": category,
            "name": name,
            "content": content[:5000],
            "updated_at": time.time(),
        })
        await redis.expire(key, 60 * 60 * 24 * 30)  # 30 day TTL

        # Add to category index
        await redis.sadd(f"{BRIDGE_NS}vault_index:{category}", name)
        # Add to global search index
        await redis.zadd(f"{BRIDGE_NS}vault_recent", {f"{category}:{name}": time.time()})
        await redis.zremrangebyrank(f"{BRIDGE_NS}vault_recent", 0, -1001)  # Keep last 1000

        log.info("vault_entry_synced_to_redis", category=category, name=name)

    async def search_swarm_history(self, query: str, max_results: int = 5) -> list[dict]:
        """Search Redis-backed swarm history for results matching a query.

        Simple keyword matching against goals and final answers.
        Returns results with a relevance score based on keyword overlap.
        """
        redis = await get_redis()
        session_ids = await redis.lrange(f"{BRIDGE_NS}results_index", 0, 99)
        query_words = set(query.lower().split())
        scored: list[tuple[float, dict]] = []

        for sid in session_ids:
            raw = await redis.get(f"{BRIDGE_NS}result:{sid}")
            if not raw:
                continue
            record = json.loads(raw)
            # Score by keyword overlap in goal + answer
            text = f"{record.get('goal', '')} {record.get('final_answer', '')}".lower()
            text_words = set(text.split())
            overlap = len(query_words & text_words)
            if overlap > 0:
                relevance = overlap / max(1, len(query_words))
                record["relevance"] = round(relevance, 3)
                scored.append((relevance, record))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:max_results]]

    async def get_vault_stats(self) -> dict:
        """Get vault statistics from Redis + disk."""
        redis = await get_redis()

        # Count entities synced to Redis
        redis_categories = await redis.keys(f"{BRIDGE_NS}vault_index:*")
        redis_entity_count = 0
        for cat_key in redis_categories:
            redis_entity_count += await redis.scard(cat_key)

        recent_count = await redis.zcard(f"{BRIDGE_NS}vault_recent")

        # Disk stats from vault
        from nanobot.knowledge.vault import vault
        disk_stats = vault.get_stats()

        return {
            "disk": disk_stats,
            "redis_synced_entities": redis_entity_count,
            "redis_recent_entries": recent_count,
            "redis_categories": len(redis_categories),
        }

    async def bulk_sync_vault_to_redis(self) -> int:
        """Bulk sync all vault entities to Redis for fast retrieval.

        Call this at startup or after a rebuild to populate the Redis cache.
        """
        from nanobot.knowledge.vault import vault

        synced = 0
        for category in ["people", "companies", "projects", "topics",
                         "decisions", "commitments", "meetings"]:
            cat_dir = vault.root / category
            if not cat_dir.exists():
                continue
            for md_file in cat_dir.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    name = md_file.stem.replace("-", " ").title()
                    await self.sync_vault_entry(category, name, content[:3000])
                    synced += 1
                except Exception as e:
                    log.warning("bulk_sync_entry_failed", file=str(md_file), error=str(e))

        log.info("vault_bulk_synced_to_redis", entries=synced)
        return synced

    async def get_bridge_status(self) -> dict:
        """Get bridge health and sync status."""
        redis = await get_redis()

        result_count = await redis.llen(f"{BRIDGE_NS}results_index")
        memory_exists = NELLIE_MEMORY_FILE.exists()
        history_exists = NELLIE_HISTORY_FILE.exists()

        history_size = 0
        if history_exists:
            history_size = NELLIE_HISTORY_FILE.stat().st_size

        # Vault Redis sync stats
        redis_vault_count = 0
        try:
            redis_vault_count = await redis.zcard(f"{BRIDGE_NS}vault_recent")
        except Exception:
            pass

        return {
            "status": "operational",
            "nellie_memory_exists": memory_exists,
            "nellie_history_exists": history_exists,
            "nellie_history_size_kb": round(history_size / 1024, 1),
            "persisted_results": result_count,
            "redis_vault_entities": redis_vault_count,
            "sync_cursor": self._last_sync_cursor,
            "workspace_path": str(NELLIE_WORKSPACE),
        }


# Singleton
memory_bridge = NellieMemoryBridge()
