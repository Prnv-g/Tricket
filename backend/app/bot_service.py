import asyncio
import logging
import secrets
import statistics

import httpx
import joblib

from .config import ROOT, TURNSTILE_SECRET
from .errors import Problem
from .inventory import now_ms, prefix
from .redis_client import redis

logger = logging.getLogger("seatsurge")
MODEL = None


def load_model():
    global MODEL
    try:
        MODEL = joblib.load(ROOT / "ai/bot_model.joblib")
    except Exception:
        logger.warning('{"event":"bot_model_fallback","screening":"rules"}')


async def record(sid, action, failed=False):
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(f"bot:req:{sid}")
        pipe.expire(f"bot:req:{sid}", 60, nx=True)
        pipe.incr(f"bot:burst:{sid}")
        pipe.expire(f"bot:burst:{sid}", 5, nx=True)
        if failed and action == "hold":
            pipe.incr(f"bot:failed:{sid}")
            pipe.expire(f"bot:failed:{sid}", 600, nx=True)
        await pipe.execute()


def risk(features):
    requests, median, variation, moves, clicks, age, failed, burst, abandoned = features
    reasons = []
    if requests >= 15 or burst >= 8:
        reasons.append("High request rate")
    if median and median < 600 and variation < 30:
        reasons.append("Unnaturally regular action intervals")
    if moves < 2 and clicks > 5:
        reasons.append("Low interaction activity for the click volume")
    if failed >= 3 or abandoned >= 3:
        reasons.append("Repeated failed or abandoned reservations")
    rule = .98 if requests >= 35 or burst >= 16 else min(.91, .30 * len(reasons))
    if MODEL is None:
        return rule, reasons
    probability = float(MODEL.predict_proba([features])[0, 1])
    # Sparse client telemetry alone cannot distinguish keyboard and touch users.
    if not reasons:
        probability = min(probability, .39)
    return max(rule, probability), reasons


async def assess(event, sid, behavior):
    await record(sid, "join")
    async with redis.pipeline(transaction=False) as pipe:
        requests, burst, failed, created, abandoned = await (
            pipe.get(f"bot:req:{sid}").get(f"bot:burst:{sid}").get(f"bot:failed:{sid}")
            .get(f"bot:created:{sid}").hget(prefix(event) + "abandoned", sid).execute()
        )
    clock = await now_ms()
    age = max(0, (clock - int(created or clock)) / 1000)
    vector = [int(requests or 0), statistics.median(behavior.intervals) if behavior.intervals else 0,
              statistics.pstdev(behavior.intervals) if len(behavior.intervals) > 1 else 0,
              behavior.moves, behavior.clicks, age, int(failed or 0), int(burst or 0), int(abandoned or 0)]
    score, reasons = await asyncio.to_thread(risk, vector)
    await redis.set(f"bot:risk:{sid}", f"{score:.4f}", ex=600)
    return score, reasons


async def verify(event, sid, payload):
    if TURNSTILE_SECRET:
        if not payload.turnstile_token:
            raise Problem(403, "TURNSTILE_REQUIRED", "Complete the security verification to join.")
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                result = await client.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                                           data={"secret": TURNSTILE_SECRET, "response": payload.turnstile_token})
                result.raise_for_status()
            if result.json().get("success") is not True:
                raise Problem(403, "TURNSTILE_REQUIRED", "Security verification expired. Please try again.")
        except (httpx.HTTPError, ValueError) as error:
            raise Problem(503, "VERIFICATION_UNAVAILABLE", "Security verification is temporarily unavailable.") from error
    score, reasons = await assess(event, sid, payload.behavior)
    if score >= .90:
        await redis.hincrby("metrics:counts", "bot_blocks", 1)
        raise Problem(403, "BOT_BLOCK", "Queue access blocked. " + ". ".join(reasons) + ".")
    key = f"bot:challenge:{sid}"
    if payload.challenge_answer is not None:
        challenge = await redis.getdel(key)
        if challenge and secrets.compare_digest(challenge, payload.challenge_answer.strip()):
            await redis.hincrby("metrics:counts", "bot_allowed", 1)
            return
    if score >= .50 or payload.challenge_answer is not None:
        a, b = secrets.randbelow(8) + 2, secrets.randbelow(8) + 2
        await redis.set(key, str(a + b), ex=120)
        await redis.hincrby("metrics:counts", "bot_challenges", 1)
        raise Problem(403, "BOT_CHALLENGE", f"What is {a} + {b}?")
    await redis.hincrby("metrics:counts", "bot_allowed", 1)
