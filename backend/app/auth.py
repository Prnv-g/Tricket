import hashlib
import hmac
import re
import secrets

from fastapi import Request, WebSocket

from .config import ADMIN_TOKEN, ORIGINS, SESSION_SECRET, TRUSTED_PROXY
from .errors import Problem
from .redis_client import SCRIPTS

COOKIE = "seatsurge"
TOKEN = re.compile(r"[0-9a-f]{32}")


def new_id():
    return secrets.token_hex(16)


def sign(sid):
    digest = hmac.new(SESSION_SECRET, sid.encode(), hashlib.sha256).hexdigest()
    return f"{sid}.{digest}"


def session(conn: Request | WebSocket, required=True):
    signed = conn.cookies.get(COOKIE, "")
    sid, _, _ = signed.partition(".")
    if TOKEN.fullmatch(sid) and hmac.compare_digest(sign(sid), signed):
        return sid
    if required:
        raise Problem(401, "SESSION_REQUIRED", "Start a booking session first.")
    return None


def fingerprint(request):
    direct = request.client.host if request.client else "unknown"
    ip = request.headers.get("x-real-ip", direct) if direct == TRUSTED_PROXY else direct
    return hmac.new(SESSION_SECRET, ip.encode(), hashlib.sha256).hexdigest()[:24]


def require_origin(request: Request | WebSocket, required=False):
    origin = request.headers.get("origin")
    if (origin or required) and origin not in ORIGINS:
        raise Problem(403, "ORIGIN", "This origin is not allowed.")


def admin(request: Request):
    bearer = request.headers.get("authorization", "").encode()
    if not ADMIN_TOKEN or not hmac.compare_digest(bearer, f"Bearer {ADMIN_TOKEN}".encode()):
        raise Problem(401, "ADMIN_REQUIRED", "Enter a valid operations credential.")


async def limit(request, action, user_limit, ip_limit, sid=None, seconds=60):
    keys = [f"rate:{action}:ip:{fingerprint(request)}"]
    limits = [ip_limit]
    if sid:
        keys.append(f"rate:{action}:user:{sid}")
        limits.append(user_limit)
    retry = await SCRIPTS["rate_limit"](keys=keys, args=[*limits, seconds])
    if retry:
        raise Problem(429, "RATE_LIMIT", "Too many requests. Please wait and try again.", retry)
