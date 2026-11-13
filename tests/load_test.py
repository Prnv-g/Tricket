"""Paced end-to-end HTTP seat-map load against the shared event cache."""
import argparse
import asyncio
import json
import math
import os
import time

import httpx


async def run(base, rate, seconds):
    attempted = rate * seconds
    times, responses = [], []
    jobs = asyncio.Queue()
    workers = min(32, attempted)
    ready = asyncio.Barrier(workers + 1)

    async def worker():
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        async with httpx.AsyncClient(trust_env=False, base_url=base, timeout=4, limits=limits) as client:
            warmup = await client.get("/api/seatmap/neon-nights")
            if warmup.status_code != 200:
                await ready.abort()
                warmup.raise_for_status()
            await ready.wait()
            while (scheduled := await jobs.get()) is not None:
                try:
                    response = await client.get("/api/seatmap/neon-nights")
                    responses.append(response.status_code)
                except httpx.HTTPError:
                    responses.append(0)
                times.append((time.perf_counter() - scheduled) * 1000)

    async with asyncio.TaskGroup() as group:
        for _ in range(workers):
            group.create_task(worker())
        await ready.wait()
        started = time.perf_counter()
        for index in range(attempted):
            scheduled = started + index / rate
            await asyncio.sleep(max(0, scheduled - time.perf_counter()))
            jobs.put_nowait(scheduled)
        for _ in range(workers):
            jobs.put_nowait(None)
    elapsed = time.perf_counter() - started
    times.sort()
    ok = responses.count(200)
    def percentile(fraction):
        return round(times[math.ceil(len(times) * fraction) - 1], 2)
    return {"requested_rps": rate, "attempted": attempted, "succeeded": ok, "seconds": round(elapsed, 3),
            "throughput_rps": round(attempted / elapsed, 2), "successful_rps": round(ok / elapsed, 2),
            "success_rate": round(ok / attempted, 4), "p50_ms": percentile(.5), "p95_ms": percentile(.95),
            "error_rate": round(1 - ok / attempted, 4)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.getenv("TEST_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--rate", type=int, default=500)
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.rate <= 2000 or not 1 <= args.seconds <= 60:
        parser.error("rate must be 1–2000 and seconds must be 1–60")
    print(json.dumps(asyncio.run(run(args.base, args.rate, args.seconds)), indent=2))
