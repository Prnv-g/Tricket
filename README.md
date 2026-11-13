# SeatSurge

SeatSurge is a flash-sale ticketing demo for Neon Nights at SeatSurge Arena in Hyderabad. Two FastAPI replicas share a 5,200-seat event, a FIFO waiting room, live inventory, and a simulated checkout.

## Start the stack

Install Docker with Compose v2. From this directory, copy the sample configuration and replace `SESSION_SECRET` and `ADMIN_TOKEN` with long random values. The sample enables the isolated Chaos Arena.

```sh
cp .env.example .env
docker compose up --build -d
docker compose ps
curl -fsS http://localhost:8080/api/health
```

Open [http://localhost:8080](http://localhost:8080). Use the value of `ADMIN_TOKEN` at [http://localhost:8080/admin](http://localhost:8080/admin). The port binds to local loopback. If you run plain `docker compose up --build -d` without a local `.env`, the customer flow uses local defaults and admin access is disabled.

Book tickets to join the shared waiting room. Select one seat or a contiguous group of up to six. The accessible picker shows 13 seats at a time. Reserve the group to start its two-minute hold. Refresh on checkout to recover the same reservation deadline. Try a decline or timeout before approving payment, then print the issued tickets. Waiting sessions are admitted in order as slots open. To observe a visible waiting queue with two browsers, set `ADMISSION_CAPACITY=1` and restart the API containers.

The event and tier prices are seeded in PostgreSQL. All amounts use whole Indian rupees. The simulated provider accepts no card data and makes no external charges. Turnstile is optional. Set both `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET` to enable it and configure your hostname with Cloudflare.

## Run the tests

Use Python 3.12 locally to run tests through NGINX. Set `ADMIN_TOKEN` in your shell to the same value configured in `.env`. In PowerShell, use `Copy-Item .env.example .env` and `$env:ADMIN_TOKEN = "your-value"`.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
export ADMIN_TOKEN='the-value-from-your-env-file'
python -m pytest -q -s backend/tests
python tests/load_test.py --rate 500 --seconds 10
python tests/chaos_test.py api-failure
python tests/chaos_test.py redis-failure
```

Set `DEMO_MODE=true` in `.env` for the isolated tests. The suite runs the same service code as the application against unique temporary events. The load generator sends paced HTTP requests through NGINX and reports achieved throughput, success rate, and latency percentiles. Each chaos script creates a session and a temporary hold in the live event and releases it on completion. Run these scripts against a dedicated demo stack because they stop shared services.

To verify the direct WebSocket path across both replicas from the host, temporarily publish their ports to loopback with the following local Compose override. Allow the origin of the gateway in `APP_ORIGINS`.

```yaml
services:
  api-a:
    ports: ["127.0.0.1:8081:8000"]
  api-b:
    ports: ["127.0.0.1:8082:8000"]
```

Save it as `compose.test.yml`, then run:

```sh
docker compose -f docker-compose.yml -f compose.test.yml up -d
TEST_API_A=http://127.0.0.1:8081 TEST_API_B=http://127.0.0.1:8082 python -m pytest -q -s backend/tests
TEST_API_A=http://127.0.0.1:8081 python tests/chaos_test.py api-failure
```

## Demonstrate failover manually

With a reservation active, stop one replica and refresh the booking page. Check the response header to see which replica served it. Restart the stopped replica after the demo.

```sh
docker compose stop api-a
curl -si http://localhost:8080/api/health
docker compose start api-a
```

To interrupt Redis and recover safely:

```sh
docker compose stop redis
curl -si http://localhost:8080/api/health
docker compose start redis
curl -si http://localhost:8080/api/health
curl -si http://localhost:8080/api/seatmap/neon-nights/version
docker compose logs --tail=60 api-a api-b redis postgres
```

Booking writes require both dependencies. After Redis restarts, wait for both health and the inventory version endpoint to return 200. An API replica rebuilds Redis from committed PostgreSQL rows when the Redis server identity changes. If the APIs started before Redis or PostgreSQL were ready, use `docker compose restart api-a api-b` after the dependencies recover. Persistent volumes retain data across ordinary Compose restarts.

## Reproduce bot evaluation

```sh
cd backend
python -m ai.train
```

The saved report is in `backend/ai/evaluation.json`. Training uses synthetic sessions and a held-out 25% split. The classifier is a demo screening model. With no model file, the application uses its deterministic behavior rules and logs the fallback.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the request paths and [DECISIONS.md](DECISIONS.md) for safety and scaling tradeoffs.
