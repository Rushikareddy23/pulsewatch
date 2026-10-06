import asyncio
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import worker
from app.checker import CheckResult, Target, check
from app.models import Check, Incident, Monitor, Notification, User
from app.stats import downsample, monitor_stats, percentile

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
OK = CheckResult(True, 200, 42.0, None)
FAIL = CheckResult(False, 503, 10.0, "expected 200, got 503")


def seed(session_factory, n=1, **kw):
    with session_factory() as db:
        u = User(email="owner@example.com", password_hash="x")
        db.add(u)
        db.flush()
        ms = [Monitor(user_id=u.id, name=f"m{i}", url=f"https://site{i}.example/", next_check_at=T0, **kw)
              for i in range(n)]
        db.add_all(ms)
        db.commit()
        return [m.id for m in ms]


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def lease(sf, mid, minute, timeout=10):
    """Claim a monitor as a worker would, at a given minute."""
    with sf() as db:
        m = db.get(Monitor, mid)
        m.next_check_at, m.lease_token, m.lease_expires_at, m.timeout_s = at(minute), None, None, timeout
        db.commit()
        [c] = worker.claim_due(db, at(minute), 1)
        return c


def record(sf, mid, r, minute):
    c = lease(sf, mid, minute)
    with sf() as db:
        return worker.record_result(db, c, r, at(minute) + timedelta(seconds=1))


def state(sf, mid):
    with sf() as db:
        m = db.get(Monitor, mid)
        return (m.status, m.consecutive_failures, db.query(Incident).filter_by(monitor_id=mid).all(),
                db.query(Notification).filter_by(monitor_id=mid).order_by(Notification.id).all())


class FlakyNotifier:
    def __init__(self, fail_times=0):
        self.fail_times, self.sent = fail_times, []

    def send(self, to, subject, body):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("SMTP down")
        self.sent.append(subject)


def test_incident_lifecycle_with_failure_threshold(session_factory):
    [mid] = seed(session_factory)
    record(session_factory, mid, OK, 0)
    record(session_factory, mid, FAIL, 1)
    status, fails, incs, notes = state(session_factory, mid)
    assert (status, fails, len(incs), len(notes)) == ("up", 1, 0, 0)  # one blip: no alert

    record(session_factory, mid, FAIL, 2)
    record(session_factory, mid, FAIL, 3)
    status, _, incs, notes = state(session_factory, mid)
    assert status == "down" and len(incs) == 1 and incs[0].resolved_at is None
    assert [n.subject[:6] for n in notes] == ["[DOWN]"]  # one alert per outage, not per check

    record(session_factory, mid, OK, 4)
    status, fails, incs, notes = state(session_factory, mid)
    assert status == "up" and fails == 0 and incs[0].resolved_at is not None
    assert notes[-1].subject.startswith("[RECOVERED]")


def test_checker_never_sends_email_itself(session_factory):
    """Alerts only reach the outbox; delivery is app.notify_worker's job."""
    [mid] = seed(session_factory)
    record(session_factory, mid, FAIL, 1)
    record(session_factory, mid, FAIL, 2)
    status, _, incs, notes = state(session_factory, mid)
    assert status == "down" and len(incs) == 1
    assert len(notes) == 1 and notes[0].sent_at is None and notes[0].attempts == 0
    assert not hasattr(worker, "deliver_notifications")


def test_pause_resume_does_not_strand_incident(session_factory, client):
    from conftest import auth_headers
    h = auth_headers(client, "owner2@example.com")
    with session_factory() as db:
        uid = db.query(User).filter_by(email="owner2@example.com").one().id
        m = Monitor(user_id=uid, name="x", url="https://x.example/", next_check_at=T0)
        db.add(m)
        db.commit()
        mid = m.id
    record(session_factory, mid, FAIL, 1)
    record(session_factory, mid, FAIL, 2)
    in_flight = lease(session_factory, mid, 3)
    assert client.patch(f"/api/monitors/{mid}", json={"is_active": False}, headers=h).json()["status"] == "pending"
    with session_factory() as db:                                # result arriving while paused is ignored
        assert worker.record_result(db, in_flight, OK, at(3) + timedelta(seconds=1)) is False
    client.patch(f"/api/monitors/{mid}", json={"is_active": True}, headers=h)
    record(session_factory, mid, OK, 4)
    status, _, incs, _ = state(session_factory, mid)
    assert status == "up" and incs[0].resolved_at is not None


def test_result_from_expired_lease_is_rejected(session_factory):
    [mid] = seed(session_factory)
    a = lease(session_factory, mid, 0, timeout=10)              # worker A, lease until 0:15
    with session_factory() as db:                               # A finishes too late
        assert worker.record_result(db, a, OK, at(0) + timedelta(seconds=16)) is False
    with session_factory() as db:
        assert db.query(Check).count() == 0


def test_result_from_superseded_claim_is_rejected(session_factory):
    [mid] = seed(session_factory)
    a = lease(session_factory, mid, 0, timeout=10)
    b = lease(session_factory, mid, 1, timeout=10)               # lease expired; worker B reclaimed
    with session_factory() as db:
        assert worker.record_result(db, a, FAIL, at(1) + timedelta(seconds=2)) is False  # A's token is stale
        assert worker.record_result(db, b, OK, at(1) + timedelta(seconds=3)) is True
    with session_factory() as db:
        assert [c.ok for c in db.query(Check).all()] == [True]
        assert db.get(Monitor, mid).lease_token is None           # lease released after recording


def test_leased_monitor_cannot_be_claimed_until_lease_expires(session_factory):
    [mid] = seed(session_factory, interval_s=30, timeout_s=30)
    with session_factory() as db:
        assert len(worker.claim_due(db, T0, 10)) == 1             # lease = 30 s timeout + 5 s margin
    with session_factory() as db:
        assert worker.claim_due(db, T0 + timedelta(seconds=31), 10) == []  # due, but still leased
        assert len(worker.claim_due(db, T0 + timedelta(seconds=35), 10)) == 1


def test_claim_due_schedules_next_check(session_factory):
    ids = seed(session_factory, n=3, interval_s=60)
    with session_factory() as db:
        assert {c.target.monitor_id for c in worker.claim_due(db, T0, 10)} == set(ids)
    with session_factory() as db:
        assert worker.claim_due(db, T0 + timedelta(seconds=30), 10) == []
        assert len(worker.claim_due(db, T0 + timedelta(seconds=60), 10)) == 3


def test_inactive_monitors_are_skipped(session_factory):
    seed(session_factory, n=2, is_active=False)
    with session_factory() as db:
        assert worker.claim_due(db, T0, 10) == []


def test_one_bad_result_does_not_lose_the_batch(session_factory, monkeypatch):
    ids = seed(session_factory, n=3)
    real = worker.record_result

    def sometimes_broken(db, claim, r, finished_at=None):
        if claim.target.monitor_id == ids[1]:
            raise RuntimeError("boom")
        return real(db, claim, r, finished_at)

    async def fake_check(client, t, allow_private=None):
        return OK
    monkeypatch.setattr(worker, "record_result", sometimes_broken)
    monkeypatch.setattr(worker, "check", fake_check)
    with session_factory() as db:
        for m in db.query(Monitor):
            m.next_check_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert asyncio.run(worker.run_once(session_factory, None, capacity=10)) == 3
    with session_factory() as db:
        assert {c.monitor_id for c in db.query(Check).all()} == {ids[0], ids[2]}


def test_claims_only_what_it_can_run_now(session_factory, monkeypatch):
    """With capacity 3 and 10 due monitors, only 3 are leased; the rest stay claimable."""
    seed(session_factory, n=10)
    with session_factory() as db:
        for m in db.query(Monitor):
            m.next_check_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    started = []

    async def fake_check(client, t, allow_private=None):
        started.append(t.monitor_id)
        with session_factory() as db:
            # Never more than 3 leased (some may already be recorded and released), and the
            # other 7 have never been claimed at all.
            assert db.query(Monitor).filter(Monitor.lease_token.isnot(None)).count() <= 3
            assert db.query(Monitor).filter(Monitor.next_check_at <= datetime.now(timezone.utc)).count() == 7
        return OK
    monkeypatch.setattr(worker, "check", fake_check)
    assert asyncio.run(worker.run_once(session_factory, None, capacity=3)) == 3
    with session_factory() as db:
        assert db.query(Monitor).filter(Monitor.lease_token.isnot(None)).count() == 0


def test_run_forever_keeps_slots_full_and_processes_everything(session_factory, monkeypatch):
    seed(session_factory, n=12)
    with session_factory() as db:
        for m in db.query(Monitor):
            m.next_check_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    running, peak = 0, 0

    async def fake_check(client, t, allow_private=None):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return OK
    monkeypatch.setattr(worker, "check", fake_check)
    assert asyncio.run(worker.run_forever(session_factory, None, concurrency=4, stop_when_idle=True)) == 12
    assert peak == 4
    with session_factory() as db:
        assert db.query(Check).count() == 12


def test_total_deadline_stops_a_trickling_response():
    """httpx timeouts are per read; a server sending a byte at a time could run forever."""
    import time

    async def trickle():
        for _ in range(30):
            await asyncio.sleep(0.01)
            yield b"x"

    def handler(req):
        return httpx.Response(200, content=trickle())

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            t0 = time.perf_counter()
            r = await worker.check_with_deadline(c, Target(1, "https://93.184.215.14/", "GET", 0.05, 200))
            return r, time.perf_counter() - t0
    r, elapsed = asyncio.run(go())
    assert not r.ok and "within 0.05s" in r.error
    assert elapsed < 0.2


@pytest.mark.skipif("postgresql" not in __import__("os").environ.get("TEST_DATABASE_URL", ""),
                    reason="SKIP LOCKED needs PostgreSQL")
def test_concurrent_workers_never_claim_same_monitor(session_factory):
    seed(session_factory, n=200)
    claimed: list[list[int]] = []
    barrier = threading.Barrier(4)

    def run():
        barrier.wait()
        got = []
        while True:
            with session_factory() as db:
                batch = worker.claim_due(db, T0, 7)
            if not batch:
                break
            got += [c.target.monitor_id for c in batch]
        claimed.append(got)

    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    flat = [i for c in claimed for i in c]
    assert len(flat) == 200 and len(set(flat)) == 200
    assert sum(1 for c in claimed if c) >= 2


def test_checker_connects_to_the_validated_ip(monkeypatch):
    seen = {}
    monkeypatch.setattr("app.url_safety.resolve_host", lambda h: ["93.184.215.14"])

    def handler(req):
        seen.update(host=req.url.host, header=req.headers["host"], sni=req.extensions.get("sni_hostname"))
        return httpx.Response(200)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await check(c, Target(1, "https://status.example.com/health", "GET", 5, 200), allow_private=False)
    assert asyncio.run(go()).ok
    assert seen == {"host": "93.184.215.14", "header": "status.example.com", "sni": "status.example.com"}


def test_dns_rebinding_to_private_ip_is_blocked(monkeypatch):
    monkeypatch.setattr("app.url_safety.resolve_host", lambda h: ["93.184.215.14", "10.0.0.7"])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
            return await check(c, Target(1, "https://rebind.example.com/", "GET", 5, 200), allow_private=False)
    r = asyncio.run(go())
    assert not r.ok and r.error.startswith("blocked")


def test_check_status_and_timeouts():
    def handler(req):
        if req.url.path == "/slow":
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200 if req.url.path == "/ok" else 500)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return [await check(c, Target(1, f"https://93.184.215.14/{p}", "GET", 2, 200)) for p in ("ok", "bad", "slow")]
    ok, bad, slow = asyncio.run(go())
    assert ok.ok and not bad.ok and "got 500" in bad.error and "timeout" in slow.error


def test_stats(session_factory):
    [mid] = seed(session_factory)
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        for i, lat in enumerate(range(10, 110, 10)):
            db.add(Check(monitor_id=mid, checked_at=now - timedelta(minutes=i), ok=True, latency_ms=float(lat)))
        db.add(Check(monitor_id=mid, checked_at=now, ok=False, error="x"))
        db.commit()
        s = monitor_stats(db, mid, 24)
    assert s["checks"] == 11 and s["uptime_pct"] == round(100 * 10 / 11, 3)
    assert s["avg_latency_ms"] == 55.0 and s["p95_latency_ms"] == 95.5


def test_seven_day_chart_keeps_newest_checks():
    from collections import namedtuple
    R = namedtuple("R", "checked_at ok status_code latency_ms error")
    now = datetime(2026, 1, 8, tzinfo=timezone.utc)
    since = now - timedelta(days=7)
    rows = [R(since + timedelta(minutes=i), i != 10075, 200, 50.0, None) for i in range(10080)]
    pts = downsample(rows, since, now, 500)
    assert len(pts) <= 500
    assert pts[-1]["checked_at"] == rows[-1].checked_at        # newest data present
    assert pts[0]["checked_at"] < since + timedelta(hours=1)    # oldest data present
    assert not pts[-1]["ok"] and "1 of" in pts[-1]["error"]     # a failure inside a bucket isn't hidden


def test_percentile_matches_postgres_definition():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([], 0.9) is None
