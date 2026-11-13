import json

from .auth import new_id
from .config import ADMISSION_MS, CAPACITY
from .database import one, pool
from .inventory import mutation, prefix
from .redis_client import SCRIPTS, redis


async def advance(conn, event, complete="", capacity=CAPACITY):
    updates = json.loads(await SCRIPTS["admit_queue"](
        keys=[prefix(event)], args=[capacity, ADMISSION_MS, complete],
    ))
    for update in updates:
        await conn.execute("""
            UPDATE queue_entries SET status=%s,
                admitted_until=COALESCE(%s,admitted_until),
                admitted_at=COALESCE(to_timestamp(%s::double precision/1000),admitted_at)
            WHERE event_id=%s AND session_id=%s
        """, (update["status"], update.get("until_ms"), update.get("at"), event, update["sid"]))


async def join(event, sid, capacity=CAPACITY, admit=True):
    async with mutation(event) as (conn, _):
        result = json.loads(await SCRIPTS["join_queue"](keys=[prefix(event)], args=[sid, new_id()]))
        await conn.execute("""
            INSERT INTO queue_entries(id,event_id,session_id,sequence,status)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT(event_id,session_id) DO NOTHING
        """, (result["id"], event, sid, result["sequence"], result["status"]))
        if admit:
            await advance(conn, event, capacity=capacity)
    return await status(event, sid)


async def status(event, sid):
    p = prefix(event)
    raw = await SCRIPTS["queue_status"](keys=[p], args=[sid])
    if not raw:
        return {"status": "NOT_JOINED"}
    data = json.loads(raw)
    data["ahead"] = max(0, data.get("position", 1) - 1)
    data["admissions_per_minute"] = await redis.zcard(p + "q:recent")
    data["active_hold_id"] = await redis.hget(p + "active", sid)
    if data["status"] == "COMPLETED":
        async with pool.connection() as conn:
            booking = await one(conn, """
                SELECT b.id FROM bookings b JOIN reservations r ON r.id=b.reservation_id
                WHERE r.event_id=%s AND b.session_id=%s
            """, (event, sid))
        data["booking_id"] = booking["id"] if booking else None
    return data
