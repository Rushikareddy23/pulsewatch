"""Measure checker throughput against a local test server.

Creates N monitors pointing at a local HTTP server that answers with 20-80 ms of
simulated latency (and ~5% errors), then times how fast W worker processes get
through all of them.

SAFETY: run it against a DEDICATED database whose name contains "bench". It refuses
anything else, and it only ever deletes the bench user's own data.

Usage (PostgreSQL required for multiple workers):
  createdb pulsewatch_bench
  DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pulsewatch_bench \
  python scripts/bench_worker.py --monitors 2000 --workers 4
"""
import argparse
import asyncio
import multiprocessing as mp
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ALLOW_PRIVATE_TARGETS"] = "true"  # the target server is on localhost
BENCH_EMAIL = "bench@example.com"


async def serve(port: int):
    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            await asyncio.sleep(random.uniform(0.02, 0.08))
            code = b"500 Internal Server Error" if random.random() < 0.05 else b"200 OK"
            writer.write(b"HTTP/1.1 " + code + b"\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok")
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", port, backlog=4096)
    async with server:
        await server.serve_forever()


def run_server(port):
    asyncio.run(serve(port))


def run_worker(done_q):
    import httpx
    from app.db import SessionLocal
    from app.config import settings
    from app.worker import run_forever

    async def go():
        limits = httpx.Limits(max_connections=200, max_keepalive_connections=0)  # same as production
        async with httpx.AsyncClient(limits=limits, trust_env=False) as c:
            return await run_forever(SessionLocal, c, settings.worker_concurrency, stop_when_idle=True)
    done_q.put(asyncio.run(go()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitors", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--port", type=int, default=18080)
    a = ap.parse_args()

    from sqlalchemy import func, select
    from app.db import Base, SessionLocal, engine
    from app.models import Check, Monitor, User

    if "bench" not in (engine.url.database or ""):
        sys.exit(f"Refusing to run against database '{engine.url.database}'. Create a separate "
                 "database whose name contains 'bench' (e.g. pulsewatch_bench) and point DATABASE_URL at it.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        others = db.scalar(select(func.count()).select_from(Monitor).join(User).where(User.email != BENCH_EMAIL))
        if others:
            sys.exit(f"Database contains {others} non-benchmark monitors; use an empty bench database.")
        old = db.scalar(select(User).where(User.email == BENCH_EMAIL))
        if old:
            db.delete(old)  # cascades to the bench user's monitors, checks and incidents only
            db.commit()
        u = User(email=BENCH_EMAIL, password_hash="x")
        db.add(u); db.flush()
        now = datetime.now(timezone.utc)
        db.add_all([Monitor(user_id=u.id, name=f"bench-{i}", url=f"http://127.0.0.1:{a.port}/{i}",
                            interval_s=3600, timeout_s=5, next_check_at=now) for i in range(a.monitors)])
        db.commit()

    engine.dispose()  # don't share pooled connections with child processes
    ctx = mp.get_context("spawn")
    srv = ctx.Process(target=run_server, args=(a.port,), daemon=True)
    srv.start()
    time.sleep(0.5)
    q = ctx.Queue()
    t0 = time.perf_counter()
    workers = [ctx.Process(target=run_worker, args=(q,)) for _ in range(a.workers)]
    [w.start() for w in workers]
    counts = [q.get() for _ in workers]
    [w.join() for w in workers]
    secs = time.perf_counter() - t0
    srv.terminate()

    with SessionLocal() as db:
        bench = select(Monitor.id).join(User).where(User.email == BENCH_EMAIL)
        stored = db.query(Check).filter(Check.monitor_id.in_(bench)).count()
        distinct = db.query(Check.monitor_id).filter(Check.monitor_id.in_(bench)).distinct().count()
    print(f"monitors={a.monitors} workers={a.workers}")
    print(f"checks per worker: {counts}")
    print(f"checks stored={stored} distinct monitors={distinct} duplicates={stored - distinct}")
    print(f"elapsed={secs:.2f}s  throughput={stored / secs:,.0f} checks/sec")


if __name__ == "__main__":
    main()
