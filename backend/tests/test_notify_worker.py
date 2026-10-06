import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from app import notify_worker as nw
from app.models import Monitor, Notification, User

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


def seed_notes(sf, n=1):
    with sf() as db:
        u = User(email="o@example.com", password_hash="x")
        db.add(u)
        db.flush()
        m = Monitor(user_id=u.id, name="m", url="https://m.example/")
        db.add(m)
        db.flush()
        db.add_all([Notification(monitor_id=m.id, to_email="o@example.com", subject=f"#{i}", body="b",
                                 next_attempt_at=T0) for i in range(n)])
        db.commit()


class SlowNotifier:
    """Each send takes `seconds` on the shared clock; optionally fails, or runs `during`."""
    def __init__(self, clock, seconds=0, fail_times=0, during=None, log=None):
        self.clock, self.seconds, self.fail_times, self.during = clock, seconds, fail_times, during
        self.log = log if log is not None else []

    def send(self, to, subject, body):
        if self.during:
            self.during()
        self.clock.advance(self.seconds)
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("SMTP down")
        self.log.append(subject)


def note(sf):
    with sf() as db:
        return db.query(Notification).one()


def test_reviewer_scenario_two_workers_slow_sends_no_duplicates(session_factory):
    """20 emails, 9 s per send, two workers running at the same time. Worker B runs a
    delivery WHILE worker A is in the middle of each send. Every email goes out exactly once."""
    seed_notes(session_factory, 20)
    clock, sent = Clock(), []
    b = SlowNotifier(clock, seconds=9, log=sent)
    a = SlowNotifier(clock, seconds=9, log=sent, during=lambda: nw.deliver_one(session_factory, b, clock))
    while nw.deliver_one(session_factory, a, clock) is not None:
        pass
    nw.drain(session_factory, b, clock)
    counts = Counter(sent)
    assert len(counts) == 20 and max(counts.values()) == 1
    assert clock() - T0 == timedelta(seconds=20 * 9)   # 20 sends happened, no repeats
    with session_factory() as db:
        assert db.query(Notification).filter(Notification.sent_at.is_(None)).count() == 0
        assert db.query(Notification).filter(Notification.attempts != 1).count() == 0


def test_worker_holds_at_most_one_claim(session_factory):
    seed_notes(session_factory, 5)
    clock = Clock()
    held = []

    def look():
        with session_factory() as db:
            held.append(db.query(Notification).filter(Notification.claim_token.isnot(None)).count())
    nw.drain(session_factory, SlowNotifier(clock, seconds=9, during=look), clock)
    assert held == [1, 1, 1, 1, 1]


def test_retry_delay_is_measured_from_after_the_send(session_factory):
    seed_notes(session_factory)
    clock = Clock()
    assert nw.deliver_one(session_factory, SlowNotifier(clock, seconds=9, fail_times=1), clock) == "failed"
    n = note(session_factory)
    assert nw.aware(n.next_attempt_at) == T0 + timedelta(seconds=9 + 30)  # not T0 + 30
    assert n.claim_token is None and "SMTP down" in n.last_error


def test_sent_at_is_recorded_after_the_send(session_factory):
    seed_notes(session_factory)
    clock = Clock()
    nw.deliver_one(session_factory, SlowNotifier(clock, seconds=9), clock)
    assert nw.aware(note(session_factory).sent_at) == T0 + timedelta(seconds=9)


def test_retries_with_backoff_and_sends_exactly_once(session_factory):
    seed_notes(session_factory)
    clock, sent = Clock(), []
    n = SlowNotifier(clock, fail_times=2, log=sent)
    assert nw.drain(session_factory, n, clock) == 0          # attempt 1 fails -> due at +30 s
    assert nw.drain(session_factory, n, clock) == 0          # not due yet
    clock.advance(31)
    assert nw.drain(session_factory, n, clock) == 0          # attempt 2 fails -> due at +60 s
    clock.advance(61)
    assert nw.drain(session_factory, n, clock) == 1          # attempt 3 succeeds
    clock.advance(3600)
    assert nw.drain(session_factory, n, clock) == 0          # never re-sent
    assert sent == ["#0"]


def test_no_transaction_is_held_while_sending(session_factory):
    seed_notes(session_factory)
    clock, seen = Clock(), {}

    def peek():  # another session sees the committed claim during the send
        n = note(session_factory)
        seen.update(claimed=n.claim_token is not None, attempts=n.attempts)
    nw.deliver_one(session_factory, SlowNotifier(clock, during=peek), clock)
    assert seen == {"claimed": True, "attempts": 1}


def test_crashed_worker_claim_expires_and_stale_finish_is_ignored(session_factory):
    seed_notes(session_factory)
    with session_factory() as db:
        first = nw.claim_next(db, T0)                       # worker crashes here
    with session_factory() as db:
        assert nw.claim_next(db, T0 + timedelta(seconds=nw.CLAIM_SECONDS - 1)) is None
        second = nw.claim_next(db, T0 + timedelta(seconds=nw.CLAIM_SECONDS))
        assert second is not None
        assert nw.finish(db, first, T0, None) is False       # stale token can't overwrite
        assert nw.finish(db, second, T0, None) is True


def test_gives_up_after_max_attempts(session_factory):
    seed_notes(session_factory)
    clock = Clock()
    n = SlowNotifier(clock, fail_times=100)
    for _ in range(20):
        nw.drain(session_factory, n, clock)
        clock.advance(3600)
    assert note(session_factory).attempts == nw.MAX_SEND_ATTEMPTS


@pytest.mark.skipif("postgresql" not in __import__("os").environ.get("TEST_DATABASE_URL", ""),
                    reason="SKIP LOCKED needs PostgreSQL")
def test_parallel_slots_across_workers_never_double_send(session_factory):
    seed_notes(session_factory, 60)
    sent, lock = [], threading.Lock()

    class Slow:
        def send(self, to, subject, body):
            time.sleep(0.01)
            with lock:
                sent.append(subject)
    barrier = threading.Barrier(6)  # e.g. 2 workers x 3 slots

    def run():
        barrier.wait()
        nw.drain(session_factory, Slow())
    ts = [threading.Thread(target=run) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(sent) == 60 and len(set(sent)) == 60
