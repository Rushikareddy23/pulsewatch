"""Email delivery worker (separate process from the checker).

* Runs SLOTS sending slots. Each slot claims exactly ONE notification, sends it, records the
  outcome, then claims the next. A worker never holds claims on emails it isn't sending yet,
  so another worker can always take the rest of the queue without duplicates.
* Two independent guarantees keep a claim valid for the whole send:
  1. a heartbeat thread renews the claim every CLAIM_SECONDS/3 while the send is running
     (up to MAX_HOLD_S), so even a provider without a hard deadline can't lose its claim;
  2. SMTP sends have a real total deadline (notifier.SEND_DEADLINE_S) that shuts the socket,
     so a trickling server can't keep a send alive indefinitely.
* Claim, send and finish are separate steps; no database transaction is open while sending.
* Completion and retry times use the clock AFTER the send, so a slow send can't make the
  retry back-off expire early.
* Delivery is at-least-once: if the process dies after sending but before recording it,
  the claim expires and the email is retried.

Run: python -m app.notify_worker
"""
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from .models import Notification
from .notifier import SEND_DEADLINE_S, Notifier, make_notifier
from .timeutil import aware  # noqa: F401  (re-exported for tests)

log = logging.getLogger("pulsewatch.notify")
MAX_SEND_ATTEMPTS = 6
CLAIM_SECONDS = 2 * SEND_DEADLINE_S
MAX_HOLD_S = 5 * SEND_DEADLINE_S   # stop renewing a send that is somehow still stuck
SLOTS = 4

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Outgoing:
    id: int
    token: str
    attempts: int
    claimed_until: datetime
    to: str
    subject: str
    body: str


def claim_next(db: Session, now: datetime) -> Outgoing | None:
    """Claim the single oldest deliverable notification (or None)."""
    q = (select(Notification)
         .where(Notification.sent_at.is_(None), Notification.attempts < MAX_SEND_ATTEMPTS,
                Notification.next_attempt_at <= now,
                or_(Notification.claimed_until.is_(None), Notification.claimed_until <= now))
         .order_by(Notification.id).limit(1))
    if db.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    n = db.scalar(q)
    if n is None:
        db.rollback()
        return None
    n.claim_token, n.claimed_until = str(uuid.uuid4()), now + timedelta(seconds=CLAIM_SECONDS)
    n.attempts += 1
    out = Outgoing(n.id, n.claim_token, n.attempts, n.claimed_until, n.to_email, n.subject, n.body)
    db.commit()
    return out


def finish(db: Session, o: Outgoing, now: datetime, error: str | None) -> bool:
    """Record the outcome, only if we still own the claim."""
    values = ({"sent_at": now} if error is None else
              {"last_error": error[:500], "next_attempt_at": now + timedelta(seconds=30 * 2 ** (o.attempts - 1))})
    res = db.execute(update(Notification)
                     .where(Notification.id == o.id, Notification.claim_token == o.token)
                     .values(claim_token=None, claimed_until=None, **values))
    db.commit()
    return res.rowcount == 1


def renew(db: Session, o: Outgoing, now: datetime) -> bool:
    """Extend our claim. Returns False if we no longer own it."""
    res = db.execute(update(Notification)
                     .where(Notification.id == o.id, Notification.claim_token == o.token)
                     .values(claimed_until=now + timedelta(seconds=CLAIM_SECONDS)))
    db.commit()
    return res.rowcount == 1


class Heartbeat:
    """Renews a claim in the background until stopped."""

    def __init__(self, session_factory, o: Outgoing, clock: Clock, interval_s: float | None = None):
        self.sf, self.o, self.clock = session_factory, o, clock
        self.interval = interval_s if interval_s is not None else CLAIM_SECONDS / 3
        self.stop_event = threading.Event()
        self.lost = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        started = time.monotonic()
        while not self.stop_event.wait(self.interval):
            if time.monotonic() - started > MAX_HOLD_S:
                log.error("notification %s: send still running after %ss; letting claim lapse", self.o.id, MAX_HOLD_S)
                return
            try:
                with self.sf() as db:
                    if not renew(db, self.o, self.clock()):
                        self.lost = True
                        log.error("notification %s: claim lost during send", self.o.id)
                        return
            except Exception:
                log.exception("notification %s: claim renewal failed", self.o.id)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop_event.set()
        self.thread.join()


def deliver_one(session_factory: sessionmaker, notifier: Notifier, clock: Clock = utcnow) -> str | None:
    """Claim, send and record one notification. Returns 'sent', 'failed', 'expired' or None (idle)."""
    with session_factory() as db:
        o = claim_next(db, clock())
    if o is None:
        return None
    if clock() >= aware(o.claimed_until):  # e.g. the process was paused right after claiming
        return "expired"
    with Heartbeat(session_factory, o, clock):
        try:
            notifier.send(o.to, o.subject, o.body)
            err = None
        except Exception as e:  # noqa: BLE001 - any delivery error is retried
            err = f"{type(e).__name__}: {e}"
            log.warning("notification %s failed (attempt %s): %s", o.id, o.attempts, err)
    with session_factory() as db:
        if not finish(db, o, clock(), err):  # time measured AFTER the send
            log.error("notification %s: claim lost before completion was recorded", o.id)
    return "sent" if err is None else "failed"


def drain(session_factory: sessionmaker, notifier: Notifier, clock: Clock = utcnow) -> int:
    """Deliver until nothing is due (single slot). Returns emails sent."""
    sent = 0
    while (r := deliver_one(session_factory, notifier, clock)) is not None:
        sent += r == "sent"
    return sent


def _slot(session_factory, notifier, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            if deliver_one(session_factory, notifier) is None:
                stop.wait(2)
        except Exception:
            log.exception("delivery slot failed")
            stop.wait(5)


def main() -> None:
    from .db import SessionLocal
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    notifier, stop = make_notifier(), threading.Event()
    slots = [threading.Thread(target=_slot, args=(SessionLocal, notifier, stop), daemon=True) for _ in range(SLOTS)]
    for t in slots:
        t.start()
    log.info("notification worker started with %d slots, claim %ss", SLOTS, CLAIM_SECONDS)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
