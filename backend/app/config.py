import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENT = "neon-nights"
INSTANCE = os.getenv("INSTANCE_ID", "api-a")
ORIGINS = frozenset(os.getenv("APP_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(","))
SESSION_SECRET = os.getenv("SESSION_SECRET", "seatsurge-local-demo-signing-key-change-me").encode()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TRUSTED_PROXY = os.getenv("TRUSTED_PROXY", "")
DEMO = os.getenv("DEMO_MODE", "false").lower() == "true"
SECURE = os.getenv("SECURE_COOKIES", "false").lower() == "true"
CAPACITY = max(1, int(os.getenv("ADMISSION_CAPACITY", "100")))
ADMISSION_MS = max(120, int(os.getenv("ADMISSION_SECONDS", "600"))) * 1000
HOLD_MS = 120_000
TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET", "")
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
