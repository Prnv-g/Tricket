import asyncio
import time
from collections import Counter
from contextlib import asynccontextmanager

from .auth import new_id
from .booking_service import confirmation, pay
from .bot_service import record, verify
from .database import one, pool, seed
from .errors import Problem
from .inventory import STATE_KEYS, locked, mutation, now_ms, prefix, snapshot
from .queue_service import advance, join, status
from .redis_client import redis
from .schemas import HoldRequest, Join, PaymentRequest
from .seat_service import create, release_due

TESTS = frozenset(("single-seat", "overlap", "payment-replay", "payment-failure",
                   "expiry", "bots", "reconnect", "load", "queue"))


@asynccontextmanager
async def isolated():
    event = "demo-" + new_id()
    sessions = [new_id() for _ in range(100)]
    try:
        async with pool.connection() as conn, conn.transaction():
            await seed(conn, event, 26)
            async with conn.cursor() as cursor:
                await cursor.executemany("INSERT INTO users(id,session_id) VALUES(%s,%s)",
                                         [(sid, sid) for sid in sessions])
        yield event, sessions
    finally:
        async with locked(event) as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM reservations WHERE event_id=%s", (event,))
                await conn.execute("DELETE FROM events WHERE id=%s", (event,))
                await conn.execute("DELETE FROM users WHERE session_id=ANY(%s)", (sessions,))
            p = prefix(event)
            await redis.delete(*(p + key for key in (*STATE_KEYS, "abandoned", "dirty")))
            await redis.delete(*(f"bot:{field}:{sid}" for field in ("req", "burst", "risk") for sid in sessions[:1]))


async def attempt(awaitable):
    try:
        return await awaitable
    except Problem as error:
        return error.code


async def run(test):
    started = time.perf_counter()
    attempted = succeeded = rejected = duplicates = charges = 0
    details = {}
    async with isolated() as (event, sessions):
        async def hold(index, seats, duration=120000):
            return await create(HoldRequest(event_id=event, seat_ids=seats, idempotency_key=new_id()),
                                sessions[index], duration)

        async def payment(reservation, key, mode="success"):
            return await pay(PaymentRequest(event_id=event, reservation_id=reservation,
                                            idempotency_key=key, mode=mode), sessions[0])

        if test in ("single-seat", "overlap"):
            groups = [[1]] * 100 if test == "single-seat" else [list(range(1, 7)), list(range(4, 10))]
            for sid in sessions[:len(groups)]:
                await join(event, sid, admit=False)
            async with mutation(event) as (conn, _):
                await advance(conn, event, capacity=100)
            results = await asyncio.gather(*(attempt(hold(index, seats)) for index, seats in enumerate(groups)))
            winners = [result for result in results if isinstance(result, dict)]
            occupied = (await snapshot(event))["occupied"]
            attempted, succeeded = len(groups), len(winners)
            rejected = attempted - succeeded
            duplicates = sum(count - 1 for count in Counter(
                seat for winner in winners for seat in winner["seat_ids"]
            ).values() if count > 1)
            passed = succeeded == 1 and set(occupied) == set(winners[0]["seat_ids"]) and duplicates == 0
        elif test in ("payment-replay", "payment-failure"):
            await join(event, sessions[0])
            reservation = (await hold(0, [1, 2, 3]))["id"]
            key = new_id()
            mode = "success" if test == "payment-replay" else "timeout"
            attempted = 12 if test == "payment-replay" else 3
            results = await asyncio.gather(*(payment(reservation, key, mode) for _ in range(attempted)))
            async with pool.connection() as conn:
                stats = await one(conn, """
                    SELECT (SELECT count(*) FROM payments WHERE reservation_id=%s) AS attempts,
                           (SELECT count(*) FROM payments WHERE reservation_id=%s AND status='SUCCEEDED') AS charges,
                           (SELECT count(*) FROM tickets WHERE event_id=%s) AS tickets,
                           (SELECT count(*) FROM bookings WHERE reservation_id=%s) AS bookings
                """, (reservation, reservation, event, reservation))
            succeeded = sum(result["status"] == "SUCCEEDED" for result in results)
            rejected = attempted - succeeded
            duplicates = max(0, stats["tickets"] - 3)
            charges = max(0, stats["charges"] - 1)
            if mode == "success":
                confirmations = await asyncio.gather(*(confirmation(sessions[0], reservation) for _ in range(5)))
                passed = (succeeded == attempted and stats == {"attempts": 1, "charges": 1, "tickets": 3, "bookings": 1}
                          and len({row["id"] for row in confirmations}) == len({row["id"] for row in results}) == 1)
            else:
                passed = (rejected == attempted and stats == {"attempts": 1, "charges": 0, "tickets": 0, "bookings": 0}
                          and set((await snapshot(event))["occupied"]) == {1, 2, 3})
            details = stats
        elif test == "expiry":
            await join(event, sessions[0])
            async with redis.pubsub() as subscriber:
                await subscriber.subscribe(prefix(event) + "seat-events")
                await subscriber.get_message(timeout=1)
                reservation = (await hold(0, [1], 200))["id"]
                await subscriber.get_message(ignore_subscribe_messages=True, timeout=1)
                await asyncio.sleep(.25)
                async with mutation(event) as (conn, _):
                    await release_due(conn, event, await now_ms())
                change = await subscriber.get_message(ignore_subscribe_messages=True, timeout=1)
            outcome = await attempt(payment(reservation, new_id()))
            attempted, succeeded, rejected = 2, 1, 1
            passed = outcome == "HOLD_EXPIRED" and not (await snapshot(event))["occupied"] and bool(change) and (
                '"status":"AVAILABLE"' in change["data"])
        elif test == "bots":
            sid = sessions[0]
            for _ in range(20):
                await record(sid, "join")
            result = await attempt(verify(event, sid, Join(event_id=event)))
            # With real Turnstile enabled, use the local scoring policy directly for the synthetic case.
            if result == "TURNSTILE_REQUIRED":
                from .bot_service import assess
                score, _ = await assess(event, sid, Join().behavior)
                result = "BOT_BLOCK" if score >= .90 else "ALLOWED"
            attempted, rejected = 1, int(result == "BOT_BLOCK")
            passed = rejected == 1
        elif test == "reconnect":
            await join(event, sessions[0])
            before = await snapshot(event)
            await hold(0, [1, 2])
            after = await snapshot(event)
            attempted, succeeded = 2, 2
            passed = before["version"] < after["version"] and after["occupied"] == {1: "HELD", 2: "HELD"}
        elif test == "queue":
            first = await join(event, sessions[0], capacity=1)
            second = await join(event, sessions[1], capacity=1)
            third = await join(event, sessions[2], capacity=1)
            replay = await join(event, sessions[1], capacity=1)
            async with mutation(event) as (conn, _):
                await advance(conn, event, complete=sessions[0], capacity=1)
            next_up = await status(event, sessions[1])
            attempted, succeeded = 4, 4
            passed = (first["status"] == "ADMITTED" and second["position"] == 1 and third["position"] == 2
                      and replay["id"] == second["id"] == next_up["id"] and next_up["status"] == "ADMITTED")
        else:
            await join(event, sessions[0])
            attempted = 250
            load_started = time.perf_counter()
            results = await asyncio.gather(*(attempt(snapshot(event)) for _ in range(attempted)))
            succeeded = sum(isinstance(result, dict) for result in results)
            rejected = attempted - succeeded
            details = {"cache_reads_per_second": round(attempted / (time.perf_counter() - load_started), 1)}
            passed = succeeded == attempted
    return {"test": test, "attempted": attempted, "succeeded": succeeded, "rejected": rejected,
            "duplicate_tickets": duplicates, "duplicate_logical_charges": charges,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1), "passed": passed,
            "details": details}
