"""
Async Redis connection pool.
Singleton pattern — one pool shared across the entire swarm.
"""

import asyncio
import os
import structlog
from redis.asyncio import Redis, ConnectionPool
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff

log = structlog.get_logger()

_pool: ConnectionPool | None = None
_lock = asyncio.Lock()

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "nq-redis-nanobot-2025")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

NS = {
    "agent_memory": "nm:agent:",
    "task_history": "nt:task:",
    "swarm_state": "ns:swarm:",
    "session": "nsess:",
    "queue": "nq:queue:",
    "fact": "nf:fact:",
    "result": "nr:result:",
}


async def get_pool() -> ConnectionPool:
    global _pool
    async with _lock:
        if _pool is None:
            retry = Retry(ExponentialBackoff(cap=10, base=1), retries=3)
            _pool = ConnectionPool(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                max_connections=50,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=10,
                retry=retry,
                retry_on_error=[ConnectionError, TimeoutError],
            )
            log.info("redis_pool_created", host=REDIS_HOST, port=REDIS_PORT)
    return _pool


async def get_redis() -> Redis:
    pool = await get_pool()
    return Redis(connection_pool=pool)


async def close_pool():
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
        log.info("redis_pool_closed")
