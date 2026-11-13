import os

from redis.asyncio import Redis

from .config import ROOT

redis = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
                       decode_responses=True, socket_connect_timeout=1.5, socket_timeout=3)
SCRIPTS = {file.stem: redis.register_script(file.read_text()) for file in (ROOT / "lua").glob("*.lua")}
