from functools import partial

from .auth import new_id
from .database import all_rows, one, pool
from .errors import Problem
from .inventory import mutation, now_ms
from .queue_service import advance
from .redis_client import redis
from .seat_service import get_hold, transition


async def booking_data(conn, sid, booking):
    record = await one(conn, """
        SELECT b.id,b.reservation_id,b.status,b.created_at,e.id AS event_id,e.title,e.venue,e.starts_at,
               p.id AS payment_id,p.amount,p.provider_reference
        FROM bookings b JOIN reservations r ON r.id=b.reservation_id JOIN events e ON e.id=r.event_id
        JOIN payments p ON p.reservation_id=r.id AND p.status='SUCCEEDED'
        WHERE b.id=%s AND b.session_id=%s
    """, (booking, sid))
    if not record:
        raise Problem(404, "BOOKING_NOT_FOUND", "Booking not found.")
    record["tickets"] = await all_rows(conn, """
        SELECT t.id,t.seat_id,s.section,s.row_number,s.seat_number,s.tier,s.price
        FROM tickets t JOIN seats s ON s.event_id=t.event_id AND s.id=t.seat_id
        WHERE t.booking_id=%s ORDER BY s.id
    """, (booking,))
    return record


async def booking_for(conn, reservation):
    return await one(conn, "SELECT id FROM bookings WHERE reservation_id=%s", (reservation,))


async def payment_data(conn, payment, sid):
    return await one(conn, """
        SELECT p.id,p.status,p.mode,p.amount,p.provider_reference,p.reservation_id,b.id AS booking_id
        FROM payments p JOIN reservations r ON r.id=p.reservation_id
        LEFT JOIN bookings b ON b.reservation_id=r.id AND p.status='SUCCEEDED'
        WHERE p.id=%s AND r.session_id=%s
    """, (payment, sid))


async def pay(payload, sid):
    event = payload.event_id
    async with mutation(event) as (conn, after):
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 787))", (payload.idempotency_key,))
        previous = await one(conn, """
            SELECT p.id,p.reservation_id,p.mode,r.session_id,r.event_id
            FROM payments p JOIN reservations r ON r.id=p.reservation_id WHERE p.idempotency_key=%s
        """, (payload.idempotency_key,))
        if previous:
            if (previous["reservation_id"], previous["mode"], previous["session_id"], previous["event_id"]) != (
                payload.reservation_id, payload.mode, sid, event
            ):
                raise Problem(409, "PAYMENT_KEY_REUSED", "This payment key belongs to a different request.")
            return await payment_data(conn, previous["id"], sid)
        hold = await get_hold(conn, event, sid, payload.reservation_id)
        if not hold:
            raise Problem(404, "HOLD_NOT_FOUND", "Reservation not found.")
        confirmed = await booking_for(conn, hold["id"])
        if confirmed:
            payment = await one(conn, "SELECT id FROM payments WHERE reservation_id=%s AND status='SUCCEEDED'", (hold["id"],))
            return await payment_data(conn, payment["id"], sid)
        if hold["status"] != "ACTIVE" or hold["expires_at"] <= await now_ms():
            raise Problem(409, "HOLD_EXPIRED", "This reservation has expired or is unavailable.")
        started = await transition(event, hold, "begin")
        if started != "OK":
            raise Problem(409, "HOLD_UNAVAILABLE", "This reservation is no longer available for payment.")
        await conn.execute("UPDATE reservations SET status='COMMITTING' WHERE id=%s", (hold["id"],))
        pricing = await one(conn, "SELECT sum(price) AS amount FROM seats WHERE event_id=%s AND id=ANY(%s)",
                            (event, hold["seat_ids"]))
        payment = new_id()
        await conn.execute("""
            INSERT INTO payments(id,reservation_id,idempotency_key,mode,status,amount)
            VALUES(%s,%s,%s,%s,'PROCESSING',%s)
        """, (payment, hold["id"], payload.idempotency_key, payload.mode, pricing["amount"]))
        if payload.mode != "success":
            clock = await now_ms()
            next_state = "ACTIVE" if hold["expires_at"] > clock else "EXPIRED"
            await conn.execute("UPDATE reservations SET status=%s WHERE id=%s", (next_state, hold["id"]))
            await conn.execute("UPDATE payments SET status='FAILED' WHERE id=%s", (payment,))
            after.append(partial(transition, event, hold, "retry"))
            after.append(partial(redis.hincrby, "metrics:counts", "payments_failed", 1))
            return await payment_data(conn, payment, sid)
        booking = new_id()
        await conn.execute("""
            INSERT INTO bookings(id,reservation_id,session_id,status) VALUES(%s,%s,%s,'CONFIRMED')
        """, (booking, hold["id"], sid))
        async with conn.cursor() as cursor:
            await cursor.executemany("INSERT INTO tickets VALUES(%s,%s,%s,%s)", [
                (new_id(), booking, event, seat) for seat in hold["seat_ids"]
            ])
        await conn.execute("UPDATE payments SET status='SUCCEEDED', provider_reference=%s WHERE id=%s",
                           (f"SIM-{payment}", payment))
        await conn.execute("UPDATE reservations SET status='CONFIRMED' WHERE id=%s", (hold["id"],))
        await advance(conn, event, complete=sid)
        after.append(partial(transition, event, hold, "sold"))
        after.append(partial(redis.hincrby, "metrics:counts", "payments_succeeded", 1))
        return await payment_data(conn, payment, sid)


async def confirmation(sid, reservation):
    async with pool.connection() as conn:
        row = await booking_for(conn, reservation)
        if not row:
            raise Problem(409, "PAYMENT_REQUIRED", "A successful payment is required before tickets can be issued.")
        return await booking_data(conn, sid, row["id"])
