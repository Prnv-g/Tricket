import json
from contextlib import asynccontextmanager

from .auth import new_id
from .config import EVENT
from .database import all_rows, one, pool
from .errors import Problem
from .redis_client import SCRIPTS, redis

STATE_KEYS = (
    "ready", "generation", "version", "seats", "holds", "active", "deadlines",
    "q:sequence", "q:entry", "q:waiting", "q:admitted", "q:recent",
)


def prefix(event):
    return f"event:{event}:"


@asynccontextmanager
async def locked(event):
    async with pool.connection() as conn:
        await conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 5200))", (event,))
        try:
            yield conn
        finally:
            try:
                await conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 5200))", (event,))
            except BaseException:
                await conn.close()
                raise


@asynccontextmanager
async def mutation(event):
    p = prefix(event)
    async with locked(event) as conn:
        async with conn.transaction():
            await ensure_cache(conn, event)
        await redis.set(p + "dirty", "1")
        after_commit = []
        rejection = None
        async with conn.transaction():
            try:
                yield conn, after_commit
            except Problem as error:
                # Domain rejections can follow successful independent expiry cleanup.
                rejection = error
        for project in after_commit:
            await project()
        await redis.delete(p + "dirty")
        if rejection:
            raise rejection


async def now_ms():
    secs, micros = await redis.time()
    return secs * 1000 + micros // 1000


async def ensure_cache(conn, event):
    """Rebuild under the same event lock used by hold, queue and payment writes."""
    p = prefix(event)
    async with redis.pipeline(transaction=False) as pipe:
        server, ready, dirty = await pipe.info("server").get(p + "ready").get(p + "dirty").execute()
    if ready == server["run_id"] and not dirty:
        return
    sold = await all_rows(conn, "SELECT seat_id FROM tickets WHERE event_id=%s", (event,))
    holds = await all_rows(conn, """
        SELECT r.id,r.session_id,r.status,r.expires_at,array_agg(s.seat_id ORDER BY s.seat_id) AS seats
        FROM reservations r JOIN reservation_seats s ON s.reservation_id=r.id
        WHERE r.event_id=%s AND r.status IN ('ACTIVE','COMMITTING') GROUP BY r.id
    """, (event,))
    entries = await all_rows(conn, """
        SELECT id,session_id,sequence,status,admitted_until FROM queue_entries WHERE event_id=%s
    """, (event,))
    generation = new_id()
    occupied = {}
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(*(p + key for key in STATE_KEYS))
        for hold in holds:
            pipe.hset(p + "holds", hold["id"], json.dumps(hold))
            pipe.hset(p + "active", hold["session_id"], hold["id"])
            pipe.zadd(p + "deadlines", {hold["id"]: hold["expires_at"]})
            occupied.update({seat: hold["id"] for seat in hold["seats"]})
        occupied.update({row["seat_id"]: "SOLD" for row in sold})
        if occupied:
            pipe.hset(p + "seats", mapping=occupied)
        for entry in entries:
            sid = entry.pop("session_id")
            entry["until_ms"] = entry.pop("admitted_until")
            pipe.hset(p + "q:entry", sid, json.dumps(entry))
            if entry["status"] == "WAITING":
                pipe.zadd(p + "q:waiting", {sid: entry["sequence"]})
            if entry["status"] == "ADMITTED":
                pipe.zadd(p + "q:admitted", {sid: entry["until_ms"]})
        pipe.set(p + "q:sequence", max((row["sequence"] for row in entries), default=0))
        pipe.set(p + "generation", generation)
        pipe.set(p + "version", 0)
        pipe.set(p + "ready", server["run_id"])
        pipe.delete(p + "dirty")
        pipe.publish(p + "seat-events", json.dumps({"generation": generation, "version": 0, "reset": True}))
        pipe.publish(p + "queue-events", "changed")
        await pipe.execute()


async def invalidate(event):
    await redis.delete(prefix(event) + "ready")


async def snapshot(event, full=True):
    result = await SCRIPTS["seatmap"](keys=[prefix(event)], args=["full" if full else "version"])
    if not result:
        raise Problem(503, "INVENTORY_RECOVERY", "Inventory is reconciling. Try again shortly.")
    data = {"generation": result[0], "version": int(result[1])}
    if full:
        states = result[2]
        data["occupied"] = {
            int(seat): "SOLD" if value == "SOLD" else "HELD"
            for seat, value in zip(states[::2], states[1::2])
        }
    return data


def seat_info(seat):
    section, offset = divmod(seat - 1, 260)
    row, number = divmod(offset, 13)
    tier, price = ("Front Row", 5499) if section < 4 else (
        ("Lower Bowl", 3299) if section < 12 else ("Upper Bowl", 1799)
    )
    return {"id": seat, "section": section + 1, "row": row + 1, "number": number + 1,
            "tier": tier, "price": price}


async def recommendations(payload):
    state = await snapshot(payload.event_id)
    capacity = 5200
    if payload.event_id != EVENT:
        async with pool.connection() as conn:
            row = await one(conn, "SELECT capacity FROM events WHERE id=%s", (payload.event_id,))
            capacity = row["capacity"]
    groups = []
    for start in range(1, capacity + 1, 13):
        row_seats = range(start, min(start + 13, capacity + 1))
        info = seat_info(start)
        if (payload.tier and info["tier"] != payload.tier) or (
            payload.max_price and info["price"] * payload.count > payload.max_price
        ):
            continue
        run = []
        for seat in (*row_seats, -1):
            if seat > 0 and seat not in state["occupied"]:
                run.append(seat)
                continue
            for index in range(len(run) - payload.count + 1):
                group = run[index:index + payload.count]
                fragment = int(index == 1) + int(len(run) - index - payload.count == 1)
                center = (group[0] + group[-1]) / 2 - start
                proximity = abs(center - 6) if payload.preference == "center" else min(center, 12 - center)
                groups.append(((fragment, proximity, info["row"], group[0]), group))
            run = []
    return [{"seat_ids": group, "price": seat_info(group[0])["price"] * len(group)}
            for _, group in sorted(groups)[:4]]
