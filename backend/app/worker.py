"""Checker worker.

Scheduling model
* Work is claimed according to free capacity: a monitor is only claimed when a slot is free
  to run it immediately, so its lease starts when its check starts (nothing waits in a queue
  while its lease counts down).
* Each claim gets a unique token and a lease of `timeout + LEASE_MARGIN_S`. Every check runs
  under a TOTAL deadline of `timeout` (DNS + connect + TLS + full response), so it always
  finishes before its lease expires.
* `record_result` accepts a result only if the monitor still holds the same token and the
  lease hasn't expired; otherwise the result is discarded (another worker may own it now).
* Rows are claimed with SELECT ... FOR UPDATE SKIP LOCKED in short transactions; no DB
  transaction is ever held during network I/O. Email is sent by a separate process
  (app.notify_worker), never from this loop.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .checker import CheckResult, Target, check
from .config import settings
from .models import Check, Incident, Monitor, Notification
from .timeutil import aware

log = logging.getLogger("pulsewatch.worker")
LEASE_MARGIN_S = 5


@dataclass(frozen=True)
class Claim:
    target: Target
    token: str
    started_at: datetime
    lease_expires_at: datetime


def _locking(db: Session) -> bool:
    return db.bind.dialect.name == "postgresql"


def claim_due(db: Session, now: datetime, limit: int) -> list[Claim]:
    if limit <= 0:
        return []
    q = (select(Monitor)
         .where(Monitor.is_active.is_(True), Monitor.next_check_at <= now,
                or_(Monitor.lease_expires_at.is_(None), Monitor.lease_expires_at <= now))
         .order_by(Monitor.next_check_at).limit(limit))
    if _locking(db):
        q = q.with_for_update(skip_locked=True)
    claims = []
    for m in db.scalars(q).all():
        token = str(uuid.uuid4())
        expires = now + timedelta(seconds=m.timeout_s + LEASE_MARGIN_S)
        m.lease_token, m.lease_expires_at = token, expires
        m.next_check_at = now + timedelta(seconds=m.interval_s)
        claims.append(Claim(Target(m.id, m.url, m.method, m.timeout_s, m.expected_status), token, now, expires))
    db.commit()  # release row locks before any network I/O
    return claims


async def check_with_deadline(client: httpx.AsyncClient, t: Target) -> CheckResult:
    """Total deadline for the whole check. httpx's own timeouts are per phase / per read,
    so a server trickling bytes could otherwise run far past `timeout_s`."""
    try:
        return await asyncio.wait_for(check(client, t), timeout=t.timeout_s)
    except asyncio.TimeoutError:
        return CheckResult(False, None, None, f"timeout: no complete response within {t.timeout_s}s")


def _open_incident(db: Session, monitor_id: int) -> Incident | None:
    return db.scalar(select(Incident).where(Incident.monitor_id == monitor_id, Incident.resolved_at.is_(None)))


def record_result(db: Session, claim: Claim, r: CheckResult, finished_at: datetime | None = None) -> bool:
    """Store one result and update monitor state. Alerts go to the outbox in the same
    transaction. Returns False if the result was discarded."""
    finished_at = finished_at or datetime.now(timezone.utc)
    q = select(Monitor).where(Monitor.id == claim.target.monitor_id)
    if _locking(db):
        q = q.with_for_update()
    m = db.scalar(q)
    if m is None:  # deleted while being checked
        db.rollback()
        return False
    if m.lease_token != claim.token or finished_at > aware(m.lease_expires_at):
        db.rollback()  # lease lost or expired: another worker may own this monitor now
        log.warning("discarding result for monitor %s: lease lost/expired", m.id)
        return False
    m.lease_token, m.lease_expires_at = None, None
    last = aware(m.last_checked_at)
    if (last is not None and claim.started_at <= last) or not m.is_active:
        db.commit()  # stale or paused while in flight: release the lease, keep no result
        return False

    started_at = claim.started_at
    db.add(Check(monitor_id=m.id, checked_at=started_at, ok=r.ok, status_code=r.status_code,
                 latency_ms=r.latency_ms, error=r.error))
    m.last_checked_at = started_at
    email = m.owner.email
    incident = _open_incident(db, m.id)
    if r.ok:
        m.status, m.consecutive_failures = "up", 0
        # Driven by the incident record, not the display status, so pause/resume can't
        # leave an incident open forever.
        if incident:
            incident.resolved_at = started_at
            db.add(Notification(monitor_id=m.id, to_email=email, subject=f"[RECOVERED] {m.name} is back up",
                                body=f"{m.url} responded {r.status_code}.", next_attempt_at=started_at))
    else:
        m.consecutive_failures += 1
        # Require N failures in a row before alerting, to avoid paging on one network blip.
        if m.consecutive_failures >= settings.failure_threshold:
            m.status = "down"
            if incident is None:
                db.add(Incident(monitor_id=m.id, started_at=started_at, cause=r.error or "check failed"))
                db.add(Notification(monitor_id=m.id, to_email=email, subject=f"[DOWN] {m.name} is not responding",
                                    body=f"{m.url}: {r.error}", next_attempt_at=started_at))
    db.commit()
    return True


def _record(session_factory: sessionmaker, claim: Claim, r: CheckResult) -> None:
    with session_factory() as db:
        try:
            record_result(db, claim, r)
        except Exception:  # one bad row must not affect other checks
            db.rollback()
            log.exception("failed to record result for monitor %s", claim.target.monitor_id)


def _claim(session_factory: sessionmaker, limit: int) -> list[Claim]:
    with session_factory() as db:
        return claim_due(db, datetime.now(timezone.utc), limit)


async def _run_claim(session_factory, client, claim: Claim) -> None:
    r = await check_with_deadline(client, claim.target)
    await asyncio.to_thread(_record, session_factory, claim, r)


async def run_once(session_factory: sessionmaker, client: httpx.AsyncClient, capacity: int | None = None) -> int:
    """Claim at most `capacity` monitors, check them all concurrently, record results."""
    claims = await asyncio.to_thread(_claim, session_factory, capacity or settings.worker_concurrency)
    await asyncio.gather(*(_run_claim(session_factory, client, c) for c in claims))
    return len(claims)


async def run_forever(session_factory: sessionmaker, client: httpx.AsyncClient, concurrency: int,
                      stop_when_idle: bool = False) -> int:
    """Keep `concurrency` checks in flight; claim more only as slots free up."""
    inflight: set[asyncio.Task] = set()
    total = 0
    while True:
        free = concurrency - len(inflight)
        claims = await asyncio.to_thread(_claim, session_factory, free) if free else []
        total += len(claims)
        inflight |= {asyncio.create_task(_run_claim(session_factory, client, c)) for c in claims}
        if not inflight:
            if stop_when_idle:
                return total
            await asyncio.sleep(1)
            continue
        _, inflight = await asyncio.wait(inflight, timeout=1, return_when=asyncio.FIRST_COMPLETED)


def purge_old_checks(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    n = db.execute(delete(Check).where(Check.checked_at < cutoff)).rowcount
    db.commit()
    return n


async def _purge_loop(session_factory):
    while True:
        try:
            with session_factory() as db:
                log.info("purged %d old checks", await asyncio.to_thread(purge_old_checks, db))
        except Exception:
            log.exception("purge failed")
        await asyncio.sleep(3600)


async def main() -> None:
    from .db import SessionLocal
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # No keep-alive: each check opens a fresh connection to the validated IP. This measures
    # real connect latency and stops a TLS connection made for one hostname being reused
    # for a different hostname that happens to share the same IP.
    limits = httpx.Limits(max_connections=settings.worker_concurrency, max_keepalive_connections=0)
    async with httpx.AsyncClient(limits=limits, headers={"User-Agent": "PulseWatch/1.0"}) as client:
        log.info("checker started (concurrency=%d)", settings.worker_concurrency)
        asyncio.create_task(_purge_loop(SessionLocal))
        while True:
            try:
                await run_forever(SessionLocal, client, settings.worker_concurrency)
            except Exception:  # keep the worker alive; errors are logged and retried
                log.exception("checker loop failed")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
