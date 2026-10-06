"""Real-socket tests: a slow SMTP server and a slow provider must never let a claim lapse."""
import socket
import threading
import time
from datetime import datetime, timezone

import pytest

from app import notify_worker as nw
from app.models import Monitor, Notification, User
from app.notifier import SendDeadlineExceeded, SMTPNotifier


class TinySMTP:
    """Minimal SMTP server. Each reply is written one byte at a time with `byte_delay`
    seconds between bytes: every individual read succeeds, but the whole send is slow."""

    def __init__(self, byte_delay=0.0):
        self.byte_delay, self.messages = byte_delay, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _reply(self, conn, text):
        for b in (text + "\r\n").encode():
            conn.sendall(bytes([b]))
            if self.byte_delay:
                time.sleep(self.byte_delay)

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(conn,), daemon=True).start()

    def _session(self, conn):
        f = conn.makefile("rb")
        try:
            self._reply(conn, "220 tiny ESMTP ready")
            data_mode, body = False, []
            for raw in f:
                line = raw.decode().rstrip("\r\n")
                if data_mode:
                    if line == ".":
                        self.messages.append("\n".join(body))
                        data_mode = False
                        self._reply(conn, "250 OK queued")
                    else:
                        body.append(line)
                    continue
                cmd = line[:4].upper()
                if cmd in ("EHLO", "HELO"):
                    self._reply(conn, "250 tiny")
                elif cmd in ("MAIL", "RCPT", "RSET", "NOOP"):
                    self._reply(conn, "250 OK")
                elif cmd == "DATA":
                    data_mode = True
                    self._reply(conn, "354 go ahead")
                elif cmd == "QUIT":
                    self._reply(conn, "221 bye")
                    return
                else:
                    self._reply(conn, "502 no")
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.sock.close()


def test_fast_smtp_send_succeeds():
    srv = TinySMTP()
    try:
        SMTPNotifier("127.0.0.1", srv.port, timeout_s=1, deadline_s=5).send("a@example.com", "[DOWN] x", "body")
        assert len(srv.messages) == 1 and "[DOWN] x" in srv.messages[0]
    finally:
        srv.close()


def test_trickling_smtp_server_is_cut_off_at_the_total_deadline():
    """Reviewer's reproduction: per-read timeout 0.05 s, but every byte arrives within it.
    Without a total deadline this send takes > 1 s; it must stop at ~0.3 s."""
    srv = TinySMTP(byte_delay=0.01)
    try:
        t0 = time.perf_counter()
        with pytest.raises(SendDeadlineExceeded):
            SMTPNotifier("127.0.0.1", srv.port, timeout_s=0.05, deadline_s=0.3).send("a@example.com", "s", "b")
        elapsed = time.perf_counter() - t0
        assert 0.25 <= elapsed < 0.45, elapsed
        assert srv.messages == []
    finally:
        srv.close()


def _seed(sf):
    with sf() as db:
        u = User(email="o@example.com", password_hash="x")
        db.add(u)
        db.flush()
        m = Monitor(user_id=u.id, name="m", url="https://m.example/")
        db.add(m)
        db.flush()
        db.add(Notification(monitor_id=m.id, to_email=u.email, subject="[DOWN] m", body="b",
                            next_attempt_at=datetime.now(timezone.utc)))
        db.commit()


def test_heartbeat_keeps_the_claim_for_a_send_longer_than_the_claim(session_factory, monkeypatch):
    """Claim = 0.3 s, send = 1.0 s (e.g. a slow provider with no hard deadline). A second
    worker polls the whole time and must never get the notification."""
    monkeypatch.setattr(nw, "CLAIM_SECONDS", 0.3)
    _seed(session_factory)
    stolen, done = [], threading.Event()

    def competitor():
        while not done.is_set():
            with session_factory() as db:
                o = nw.claim_next(db, nw.utcnow())
            if o:
                stolen.append(o)
            time.sleep(0.02)

    t = threading.Thread(target=competitor)

    class SlowProvider:
        def send(self, to, subject, body):
            t.start()          # competitor starts once we hold the claim
            time.sleep(1.0)

    try:
        assert nw.deliver_one(session_factory, SlowProvider()) == "sent"
    finally:
        done.set()
        t.join()
    assert stolen == []
    with session_factory() as db:
        n = db.query(Notification).one()
        assert n.sent_at is not None and n.attempts == 1 and n.claim_token is None


def test_stuck_send_eventually_releases_its_claim(session_factory, monkeypatch):
    """Safety valve: a send stuck past MAX_HOLD_S stops renewing, so the email isn't blocked forever."""
    monkeypatch.setattr(nw, "CLAIM_SECONDS", 0.2)
    monkeypatch.setattr(nw, "MAX_HOLD_S", 0.3)
    _seed(session_factory)
    taken = []

    class Stuck:
        def send(self, to, subject, body):
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and not taken:
                with session_factory() as db:
                    o = nw.claim_next(db, nw.utcnow())
                if o:
                    taken.append(o)
                time.sleep(0.02)

    nw.deliver_one(session_factory, Stuck())
    assert taken, "claim should lapse after MAX_HOLD_S so another worker can retry"
