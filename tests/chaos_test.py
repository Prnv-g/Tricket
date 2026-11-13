"""Exercise process failover and Redis interruption on a local SeatSurge demo."""
import argparse
import asyncio
import os
import subprocess
import uuid

import httpx
from websockets.asyncio.client import connect

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8080")
A = os.getenv("TEST_API_A", BASE)
EVENT = "neon-nights"


def command(name, default):
    subprocess.run(os.getenv(name, default), shell=True, check=True)


async def healthy(client, instance=None):
    for _ in range(35):
        try:
            response = await client.get("/api/health")
            if response.status_code == 200 and (not instance or response.headers.get("X-SeatSurge-Instance") == instance):
                return response
        except httpx.HTTPError:
            pass
        await asyncio.sleep(.5)
    raise AssertionError("Service did not recover")


async def run(test):
    async with httpx.AsyncClient(trust_env=False, base_url=BASE, timeout=12) as client:
        await healthy(client)
        assert (await client.post("/api/session")).status_code == 200
        qid = (await client.post("/api/queue/join", json={})).json()["id"]
        state = (await client.get(f"/api/seatmap/{EVENT}")).json()
        seat = next(n for n in range(5199, 4800, -1) if str(n) not in state["occupied"])
        payload = {"seat_ids": [seat], "idempotency_key": uuid.uuid4().hex}
        created = await client.post("/api/holds", json=payload)
        assert created.status_code == 201, created.text
        hold = created.json()
        cookie = {"Cookie": f"seatsurge={client.cookies['seatsurge']}"}
        try:
            if test == "api-failure":
                async with connect(A.replace("http", "ws", 1)+f"/ws/seats/{EVENT}",
                                   origin=BASE, proxy=None, additional_headers=cookie) as websocket:
                    await websocket.recv()
                    try:
                        command("SEATSURGE_STOP_API", "docker compose stop api-a")
                        await asyncio.wait_for(websocket.wait_closed(), timeout=12)
                        await healthy(client, "api-b")
                        async with connect(BASE.replace("http", "ws", 1)+f"/ws/seats/{EVENT}",
                                           origin=BASE, proxy=None, additional_headers=cookie) as recovered:
                            assert await recovered.recv()
                    finally:
                        command("SEATSURGE_START_API", "docker compose start api-a")
            else:
                try:
                    command("SEATSURGE_STOP_REDIS", "docker compose stop redis")
                    for _ in range(20):
                        degraded = await client.get("/api/health")
                        if degraded.status_code == 503 and degraded.json().get("redis") is False:
                            break
                        await asyncio.sleep(.2)
                    else:
                        raise AssertionError("Redis interruption was not observed")
                    blocked = await client.post("/api/holds", json={"seat_ids":[seat-1],"idempotency_key":uuid.uuid4().hex})
                    assert blocked.status_code == 503, blocked.text
                    assert blocked.json()["error"]["code"] == "SERVICE_DEGRADED"
                finally:
                    command("SEATSURGE_START_REDIS", "docker compose start redis")
                    await healthy(client)
            for _ in range(24):
                result = await client.get("/api/queue/status")
                if result.status_code == 200 and result.json().get("id") == qid:
                    break
                await asyncio.sleep(.5)
            else:
                raise AssertionError("Queue identity was not recovered")
            assert result.json()["active_hold_id"] == hold["id"]
            for _ in range(24):
                result = await client.get(f"/api/seatmap/{EVENT}")
                if result.status_code == 200 and result.json()["occupied"].get(str(seat)) == "HELD":
                    break
                await asyncio.sleep(.5)
            else:
                raise AssertionError("Held inventory was not restored")
            print(f"{test}: PASS — same QID, same hold, recovered seat map")
        finally:
            await client.delete("/api/holds/"+hold["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test", choices=["api-failure", "redis-failure"])
    asyncio.run(run(parser.parse_args().test))
