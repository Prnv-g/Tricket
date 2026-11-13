import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import EVENT, ROOT

pool = AsyncConnectionPool(
    os.getenv("DATABASE_URL", ""), open=False, min_size=1, max_size=12, timeout=4,
    kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 3,
            "options": "-c statement_timeout=6000 -c idle_in_transaction_session_timeout=10000"},
)


async def one(conn, sql, args=()):
    return await (await conn.execute(sql, args)).fetchone()


async def all_rows(conn, sql, args=()):
    return await (await conn.execute(sql, args)).fetchall()


async def seed(conn, event=EVENT, capacity=5200):
    await conn.execute(
        """INSERT INTO events VALUES (%s, 'Neon Nights', 'SeatSurge Arena, Hyderabad',
        '2026-12-19 19:30:00+05:30', %s, %s) ON CONFLICT DO NOTHING""",
        (event, capacity, event != EVENT),
    )
    await conn.execute(
        """INSERT INTO seats
           SELECT n, %s, (n-1)/260+1, ((n-1)%%260)/13+1, (n-1)%%13+1,
           CASE WHEN n<=1040 THEN 5499 WHEN n<=3120 THEN 3299 ELSE 1799 END,
           CASE WHEN n<=1040 THEN 'Front Row' WHEN n<=3120 THEN 'Lower Bowl' ELSE 'Upper Bowl' END
           FROM generate_series(1, %s) AS g(n) ON CONFLICT DO NOTHING""",
        (event, capacity),
    )


async def initialize():
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(520011)")
        await conn.execute((ROOT / "app/schema.sql").read_text())
        await seed(conn)
