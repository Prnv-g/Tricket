import asyncio
import os
import time

import httpx
import pytest
from websockets.asyncio.client import connect

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8080")
A = os.getenv("TEST_API_A")
B = os.getenv("TEST_API_B")
TOKEN = os.getenv("ADMIN_TOKEN", "")
EVENT = "neon-nights"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", [
    "single-seat", "overlap", "payment-replay", "payment-failure", "expiry", "bots", "reconnect", "load", "queue",
])
async def test_chaos_cases(name):
    assert TOKEN, "Set ADMIN_TOKEN and enable DEMO_MODE to run the isolated suite."
    async with httpx.AsyncClient(trust_env=False, base_url=BASE, timeout=30) as client:
        response = await client.post(f"/api/admin/tests/{name}", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["passed"], result
    assert result["duplicate_tickets"] == result["duplicate_logical_charges"] == 0
    if name == "single-seat":
        assert (result["attempted"], result["succeeded"], result["rejected"]) == (100, 1, 99)


@pytest.mark.asyncio
async def test_seed_and_load_balancer():
    async with httpx.AsyncClient(trust_env=False, base_url=BASE) as client:
        event = (await client.get(f"/api/events/{EVENT}")).json()
        assert event["capacity"] == 5200
        instances = set()
        for _ in range(8):
            result = await client.get("/api/health")
            assert result.status_code == 200
            instances.add(result.headers["X-SeatSurge-Instance"])
    assert instances == {"api-a", "api-b"}, instances


@pytest.mark.asyncio
async def test_session_hold_and_websocket_across_replicas():
    if not A or not B:
        pytest.skip("Set TEST_API_A and TEST_API_B for direct replica WebSocket verification.")
    async with httpx.AsyncClient(trust_env=False, base_url=A) as client_a, httpx.AsyncClient(trust_env=False, base_url=B) as client_b:
        assert (await client_a.post("/api/session")).status_code == 200
        client_b.cookies.update(client_a.cookies)
        first = (await client_a.post("/api/queue/join", json={})).json()
        assert first["status"] == "ADMITTED", first
        second = (await client_b.get("/api/queue/status")).json()
        assert first["id"] == second["id"]
        joined_again = (await client_b.post("/api/queue/join", json={})).json()
        assert first["id"] == joined_again["id"]
        headers = {"Cookie": f"seatsurge={client_a.cookies['seatsurge']}"}
        path = f"/ws/seats/{EVENT}"
        async with connect(A.replace("http", "ws", 1)+path, origin=BASE, proxy=None, additional_headers=headers) as ws_a, (
            connect(B.replace("http", "ws", 1)+path, origin=BASE, proxy=None, additional_headers=headers)
        ) as ws_b:
            await asyncio.gather(ws_a.recv(), ws_b.recv())
            before = (await client_a.get(f"/api/seatmap/{EVENT}")).json()
            seats = next([i, i + 1] for i in range(5006, 5199) if (i - 1) // 13 == i // 13
                         and str(i) not in before["occupied"] and str(i + 1) not in before["occupied"])
            from uuid import uuid4
            payload = {"seat_ids": seats, "idempotency_key": uuid4().hex}
            start = time.perf_counter()
            hold = await client_a.post("/api/holds", json=payload)
            assert hold.status_code == 201, hold.text
            try:
                import json
                messages = await asyncio.wait_for(asyncio.gather(ws_a.recv(), ws_b.recv()), timeout=2)
                latency = time.perf_counter() - start
                for raw in messages:
                    delta = json.loads(raw)
                    assert delta["seats"] == seats and delta["status"] == "HELD"
                print(f"Cross-replica WebSocket propagation including HTTP hold: {latency * 1000:.1f} ms")
                assert latency < 1.0
                active = (await client_b.get("/api/queue/status")).json()
                assert active["active_hold_id"] == hold.json()["id"]
                replay = await client_b.post("/api/holds", json=payload)
                assert replay.json() == hold.json()
                snapshot = (await client_b.get(f"/api/seatmap/{EVENT}")).json()
                assert snapshot["version"] > before["version"]
                assert all(snapshot["occupied"][str(seat)] == "HELD" for seat in seats)
            finally:
                assert (await client_b.delete(f"/api/holds/{hold.json()['id']}")).status_code == 200
