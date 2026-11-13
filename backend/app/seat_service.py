import json
from functools import partial

from .auth import new_id
from .config import HOLD_MS
from .database import all_rows, one, pool
from .errors import Problem
from .inventory import mutation, now_ms, prefix
from .redis_client import SCRIPTS, redis


async def get_hold(conn, event, sid, reservation=None, key=None, active=False):
    return await one(conn, """
        SELECT r.id,r.event_id,r.session_id,r.status,r.expires_at,
            array_agg(rs.seat_id ORDER BY rs.seat_id) AS seat_ids
        FROM reservations r JOIN reservation_seats rs ON rs.reservation_id=r.id
        WHERE r.event_id=%s AND r.session_id=%s AND (%s::text IS NULL OR r.id=%s)
          AND (%s::text IS NULL OR r.idempotency_key=%s)
          AND (NOT %s OR r.status IN ('ACTIVE','COMMITTING'))
        GROUP BY r.id
    """, (event, sid, reservation, reservation, key, key, active))


async def transition(event, hold, operation):
    return await SCRIPTS["transition_hold"](
        keys=[prefix(event)], args=[hold["id"], hold["session_id"], operation],
    )


async def release_due(conn, event, clock, seat_ids=None):
    expired = await all_rows(conn, """
        SELECT id,session_id,status FROM reservations r
        WHERE event_id=%s AND status IN ('ACTIVE','COMMITTING') AND expires_at<=%s
        AND (%s::integer[] IS NULL OR EXISTS (
            SELECT 1 FROM reservation_seats s WHERE s.reservation_id=r.id AND s.seat_id=ANY(%s)
        )) ORDER BY expires_at LIMIT 250
    """, (event, clock, seat_ids, seat_ids))
    for hold in expired:
        # A payment transaction and this cleanup both own the event lock.
        await conn.execute("UPDATE reservations SET status='EXPIRED' WHERE id=%s", (hold["id"],))
        await transition(event, hold, "expire")


async def create(payload, sid, duration=HOLD_MS):
    event, ids = payload.event_id, sorted(payload.seat_ids)
    if len(set(ids)) != len(ids) or ids != list(range(ids[0], ids[0] + len(ids))) or (
        (ids[0] - 1) // 13 != (ids[-1] - 1) // 13
    ):
        raise Problem(422, "NOT_ADJACENT", "Choose up to six adjacent seats in the same row.")
    async with mutation(event) as (conn, _):
        original = await get_hold(conn, event, sid, key=payload.idempotency_key)
        if original:
            if original["seat_ids"] != ids:
                raise Problem(409, "KEY_REUSED", "This reservation key belongs to a different seat selection.")
            return original
        clock = await now_ms()
        admission = await one(conn, """
            SELECT 1 FROM queue_entries WHERE event_id=%s AND session_id=%s
            AND status='ADMITTED' AND admitted_until>%s
        """, (event, sid, clock))
        if not admission:
            raise Problem(403, "NOT_ADMITTED", "Wait for your queue admission before reserving seats.")
        seats = await all_rows(conn, """
            SELECT s.id FROM seats s WHERE s.event_id=%s AND s.id=ANY(%s)
            AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.event_id=s.event_id AND t.seat_id=s.id)
        """, (event, ids))
        if len(seats) != len(ids):
            raise Problem(409, "SEAT_TAKEN", "One or more of those seats are unavailable.")
        await release_due(conn, event, clock)
        occupied = await one(conn, """
            SELECT 1 FROM reservations r JOIN reservation_seats s ON s.reservation_id=r.id
            WHERE r.event_id=%s AND r.status IN ('ACTIVE','COMMITTING') AND s.seat_id=ANY(%s) LIMIT 1
        """, (event, ids))
        if occupied:
            raise Problem(409, "SEAT_TAKEN", "Another customer reserved those seats. Choose another group.")
        hold_id = new_id()
        result = await SCRIPTS["hold_seats"](keys=[prefix(event)], args=[sid, hold_id, json.dumps(ids), duration])
        if result[0] != "OK":
            messages = {
                "NOT_READY": (503, "Inventory is reconciling."),
                "NOT_ADMITTED": (403, "Your booking admission has expired."),
                "ALREADY_HOLDING": (409, "Complete or release your active reservation first."),
                "SEAT_TAKEN": (409, "Another customer reserved those seats. Choose another group."),
            }
            code, message = messages[result[0]]
            raise Problem(code, result[0], message)
        hold = json.loads(result[1])
        await conn.execute("""
            INSERT INTO reservations(id,event_id,session_id,status,expires_at,idempotency_key)
            VALUES(%s,%s,%s,'ACTIVE',%s,%s)
        """, (hold_id, event, sid, hold["expires_at"], payload.idempotency_key))
        await conn.execute("""
            INSERT INTO reservation_seats SELECT %s,%s,unnest(%s::integer[])
        """, (hold_id, event, ids))
        return {"id": hold_id, "event_id": event, "session_id": sid, "seat_ids": ids,
                "expires_at": hold["expires_at"], "status": "ACTIVE"}


async def owned(event, sid, reservation):
    async with pool.connection() as conn:
        hold = await get_hold(conn, event, sid, reservation)
    if not hold:
        raise Problem(404, "HOLD_NOT_FOUND", "Reservation not found.")
    return hold


async def cancel(event, sid, reservation):
    async with mutation(event) as (conn, after):
        hold = await get_hold(conn, event, sid, reservation)
        if not hold:
            raise Problem(404, "HOLD_NOT_FOUND", "Reservation not found.")
        if hold["status"] == "ACTIVE":
            hold["status"] = "CANCELLED"
            await conn.execute("UPDATE reservations SET status='CANCELLED' WHERE id=%s", (reservation,))
            after.append(partial(transition, event, hold, "cancel"))
        elif hold["status"] in ("CONFIRMED", "COMMITTING"):
            raise Problem(409, "HOLD_COMMITTING", "This reservation cannot be cancelled.")
        return hold
