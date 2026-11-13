import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout
from redis.exceptions import RedisError

from . import booking_service, bot_service, chaos, metrics, queue_service, realtime, seat_service
from .auth import COOKIE, admin, fingerprint, limit, new_id, require_origin, session, sign
from .config import DEMO, EVENT, INSTANCE, ORIGINS, SECURE, TURNSTILE_SECRET, TURNSTILE_SITE_KEY
from .database import all_rows, initialize, one, pool
from .errors import Problem
from .inventory import mutation, now_ms, prefix, recommendations, snapshot
from .redis_client import redis
from .schemas import EventId, HoldRequest, Join, PaymentRequest, Recommend, TokenId

logger = logging.getLogger("seatsurge")
DEPENDENCY_ERRORS = (RedisError, DatabaseError, PoolTimeout)


async def maintain():
    p = prefix(EVENT)
    while True:
        try:
            await redis.set(f"health:{INSTANCE}", "ok", ex=5)
            deadlines, waiting, admitted, ready, dirty = await (
                redis.pipeline(transaction=False).zrange(p+"deadlines", 0, 0, withscores=True)
                .zcard(p+"q:waiting").zrange(p+"q:admitted", 0, 0, withscores=True)
                .get(p+"ready").get(p+"dirty").execute()
            )
            clock = await now_ms()
            server = await redis.info("server")
            if (ready != server["run_id"] or dirty or waiting or
                (deadlines and deadlines[0][1] <= clock) or (admitted and admitted[0][1] <= clock)):
                async with mutation(EVENT) as (conn, _):
                    await seat_service.release_due(conn, EVENT, await now_ms())
                    await queue_service.advance(conn, EVENT)
        except DEPENDENCY_ERRORS as error:
            logger.warning(json.dumps({"event": "maintenance_unavailable", "type": type(error).__name__,
                                       "instance": INSTANCE}))
        await asyncio.sleep(.8)


@asynccontextmanager
async def lifespan(_):
    await pool.open()
    await initialize()
    await redis.ping()
    async with mutation(EVENT):
        pass
    bot_service.load_model()
    tasks = [asyncio.create_task(maintain()), asyncio.create_task(realtime.listen())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis.aclose()
        await pool.close()


app = FastAPI(title="SeatSurge", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(ORIGINS), allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"])


def failure(error):
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else {}
    return JSONResponse({"error": {"code": error.code, "message": error.message}}, error.status, headers)


@app.exception_handler(Problem)
async def domain_error(_, error):
    return failure(error)


@app.exception_handler(RequestValidationError)
async def validation_error(_, error):
    details = [{"location": list(item["loc"]), "message": item["msg"]} for item in error.errors()]
    return JSONResponse({"error": {"code": "INVALID_INPUT", "message": "Check the request details.",
                                   "details": details}}, 422)


@app.middleware("http")
async def request_context(request, call_next):
    identifier = new_id()
    started = time.perf_counter()
    try:
        if request.method in ("POST", "DELETE"):
            require_origin(request)
        response = await call_next(request)
    except Problem as error:
        response = failure(error)
    except DEPENDENCY_ERRORS as error:
        logger.warning(json.dumps({"event": "dependency_error", "id": identifier,
                                   "type": type(error).__name__, "instance": INSTANCE,
                                   "constraint": getattr(getattr(error, "diag", None), "constraint_name", None)}))
        response = failure(Problem(503, "SERVICE_DEGRADED", "Booking services are temporarily unavailable. Try again."))
    response.headers["X-Request-ID"] = identifier
    response.headers["X-SeatSurge-Instance"] = INSTANCE
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        await metrics.observe(identifier, request.method, request.url.path, response.status_code, started)
    return response


async def event_access(event, request):
    if event != EVENT:
        if not DEMO:
            raise Problem(404, "EVENT_NOT_FOUND", "Event not found.")
        admin(request)
        async with pool.connection() as conn:
            if not await one(conn, "SELECT 1 FROM events WHERE id=%s AND demo", (event,)):
                raise Problem(404, "EVENT_NOT_FOUND", "Event not found.")


@app.get("/api/health")
async def get_health():
    checks = await metrics.health()
    return JSONResponse(checks, 200 if checks["redis"] and checks["postgres"] else 503)


@app.get("/api/events")
async def events():
    async with pool.connection() as conn:
        return await all_rows(conn, "SELECT id,title,venue,starts_at,capacity FROM events WHERE NOT demo")


@app.get("/api/events/{event_id}")
async def event_detail(event_id: EventId, request: Request):
    await event_access(event_id, request)
    async with pool.connection() as conn:
        event = await one(conn, "SELECT id,title,venue,starts_at,capacity FROM events WHERE id=%s", (event_id,))
    try:
        state = await snapshot(event_id)
        available = event["capacity"] - len(state["occupied"])
    except (Problem, RedisError):
        available = None
    return {**event, "available": available, "turnstile_site_key": TURNSTILE_SITE_KEY if TURNSTILE_SECRET else ""}


@app.post("/api/session")
async def open_session(request: Request, response: Response):
    sid = session(request, required=False)
    await limit(request, "session", 40, 200, sid)
    if sid:
        return {"active": True}
    sid = new_id()
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO users(id,session_id) VALUES(%s,%s)", (sid, sid))
    await redis.set(f"bot:created:{sid}", await now_ms(), ex=86400)
    response.set_cookie(COOKIE, sign(sid), max_age=86400, httponly=True, secure=SECURE, samesite="lax")
    return {"active": True}


@app.post("/api/queue/join")
async def join_queue(payload: Join, request: Request):
    sid = session(request)
    await event_access(payload.event_id, request)
    await limit(request, "join", 30, 200, sid)
    current = await queue_service.status(payload.event_id, sid)
    if current["status"] != "NOT_JOINED":
        return current
    await bot_service.verify(payload.event_id, sid, payload)
    return await queue_service.join(payload.event_id, sid)


@app.get("/api/queue/status")
async def queue_status(request: Request, event_id: EventId = EVENT):
    await event_access(event_id, request)
    return await queue_service.status(event_id, session(request))


@app.get("/api/seatmap/{event_id}")
async def seat_map(event_id: EventId, request: Request):
    await event_access(event_id, request)
    return await snapshot(event_id)


@app.get("/api/seatmap/{event_id}/version")
async def seat_version(event_id: EventId, request: Request):
    await event_access(event_id, request)
    return await snapshot(event_id, full=False)


@app.post("/api/holds", status_code=201)
async def create_hold(payload: HoldRequest, request: Request):
    sid = session(request)
    await event_access(payload.event_id, request)
    await limit(request, "hold", 25, 180, sid)
    try:
        hold = await seat_service.create(payload, sid)
    except Problem:
        await bot_service.record(sid, "hold", failed=True)
        raise
    return hold


@app.get("/api/holds/{reservation_id}")
async def get_hold(reservation_id: TokenId, request: Request, event_id: EventId = EVENT):
    await event_access(event_id, request)
    return await seat_service.owned(event_id, session(request), reservation_id)


@app.delete("/api/holds/{reservation_id}")
async def cancel_hold(reservation_id: TokenId, request: Request, event_id: EventId = EVENT):
    await event_access(event_id, request)
    sid = session(request)
    await limit(request, "cancel", 25, 180, sid)
    return await seat_service.cancel(event_id, sid, reservation_id)


@app.post("/api/seats/recommend")
async def recommend(payload: Recommend, request: Request):
    await event_access(payload.event_id, request)
    await limit(request, "recommend", 45, 220, session(request))
    return await recommendations(payload)


@app.post("/api/payments/simulate")
async def simulate(payload: PaymentRequest, request: Request):
    await event_access(payload.event_id, request)
    sid = session(request)
    await limit(request, "payment", 50, 180, sid)
    return await booking_service.pay(payload, sid)


@app.get("/api/payments/{payment_id}")
async def get_payment(payment_id: TokenId, request: Request):
    async with pool.connection() as conn:
        payment = await booking_service.payment_data(conn, payment_id, session(request))
    if not payment:
        raise Problem(404, "PAYMENT_NOT_FOUND", "Payment not found.")
    return payment


@app.post("/api/bookings/confirm")
async def confirm_booking(payload: PaymentRequest, request: Request):
    await event_access(payload.event_id, request)
    sid = session(request)
    await limit(request, "confirm", 50, 180, sid)
    return await booking_service.confirmation(sid, payload.reservation_id)


@app.get("/api/bookings/{booking_id}")
async def get_booking(booking_id: TokenId, request: Request):
    async with pool.connection() as conn:
        return await booking_service.booking_data(conn, session(request), booking_id)


@app.get("/api/admin/metrics")
async def admin_metrics(request: Request):
    admin(request)
    return {**await metrics.dashboard(), "demo_mode": DEMO,
            "bot_screening": "Random forest" if bot_service.MODEL is not None else "Rules"}


@app.get("/api/admin/health")
async def admin_health(request: Request):
    admin(request)
    data = await metrics.dashboard()
    return {"health": data["health"], "instances": data["instances"]}


@app.post("/api/admin/tests/{test_name}")
async def run_test(test_name: str, request: Request):
    admin(request)
    if not DEMO or test_name not in chaos.TESTS:
        raise Problem(404, "TEST_UNAVAILABLE", "This test is unavailable.")
    await limit(request, "admin-test", 18, 35, fingerprint(request))
    return await chaos.run(test_name)


@app.websocket("/ws/queue")
async def queue_socket(websocket: WebSocket):
    await realtime.stream(websocket, queue=True)


@app.websocket("/ws/seats/{event_id}")
async def seat_socket(websocket: WebSocket, event_id: EventId):
    await realtime.stream(websocket, event=event_id)
