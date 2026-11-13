import json
import logging
import math
import time

from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout
from redis.exceptions import RedisError

from .config import EVENT, INSTANCE
from .database import one, pool
from .inventory import prefix
from .redis_client import redis

logger = logging.getLogger("seatsurge")


async def observe(request_id, method, path, status, started):
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    if status >= 500:
        logger.warning(json.dumps({"event": "request", "id": request_id, "method": method,
                                   "path": path, "status": status, "duration_ms": elapsed, "instance": INSTANCE}))
    try:
        second = int(time.time())
        async with redis.pipeline(transaction=False) as pipe:
            await (pipe.hincrby("metrics:counts", "requests", 1).incr(f"metrics:rps:{second}")
                   .expire(f"metrics:rps:{second}", 90, nx=True).lpush("metrics:latency", f"{second}:{elapsed}")
                   .ltrim("metrics:latency", 0, 3999).execute())
    except RedisError:
        pass


async def health():
    checks = {"redis": False, "postgres": False, "instance": INSTANCE}
    try:
        checks["redis"] = bool(await redis.ping())
    except RedisError:
        pass
    try:
        async with pool.connection(timeout=1) as conn:
            checks["postgres"] = bool(await one(conn, "SELECT 1"))
    except (DatabaseError, PoolTimeout):
        pass
    return checks


async def dashboard():
    checks = await health()
    if not checks["redis"]:
        return {"health": checks, "instances": {"api-a": None, "api-b": None}, "metrics": {}}
    second = int(time.time())
    p = prefix(EVENT)
    async with redis.pipeline(transaction=False) as pipe:
        counts, rps, latency, queue, admitted, recent, holds, values, ready, a, b = await (
            pipe.hgetall("metrics:counts").mget([f"metrics:rps:{sec}" for sec in range(second-10, second)])
            .lrange("metrics:latency", 0, 3999).zcard(p+"q:waiting").zcard(p+"q:admitted")
            .zcard(p+"q:recent").hlen(p+"active").hvals(p+"seats").get(p+"ready")
            .get("health:api-a").get("health:api-b").execute()
        )
    samples = sorted(float(row.split(":")[1]) for row in latency if int(row.split(":")[0]) >= second-60)
    def percentile(q):
        return samples[math.ceil(len(samples)*q)-1] if samples else None
    counts = {name: int(value) for name, value in counts.items()}
    cache_reads = counts.get("cache_hits", 0) + counts.get("cache_misses", 0)
    return {
        "health": checks, "instances": {"api-a": bool(a), "api-b": bool(b)},
        "metrics": {
            **counts, "rps": sum(int(value or 0) for value in rps) / 10,
            "p50_ms": percentile(.5), "p95_ms": percentile(.95),
            "cache_ratio": counts.get("cache_hits", 0) / cache_reads if cache_reads else None,
            "queue": queue if ready else None, "admitted": admitted if ready else None,
            "admissions_per_minute": recent if ready else None, "active_holds": holds if ready else None,
            "available": 5200 - len(values) if ready else None, "sold": values.count("SOLD") if ready else None,
        },
    }
