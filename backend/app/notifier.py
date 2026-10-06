import logging
import smtplib
import socket
import time
from email.message import EmailMessage
from typing import Protocol

from .config import settings

log = logging.getLogger("pulsewatch.notify")

# Per-operation socket timeout (one connect / one read).
SEND_TIMEOUT_S = 10
# TOTAL wall-clock limit for one send. Per-operation timeouts alone aren't enough: a server
# that keeps trickling partial responses never trips them, so every socket call is capped
# at the time remaining until this deadline (see _DeadlineSocket).
SEND_DEADLINE_S = 30


class SendDeadlineExceeded(TimeoutError):
    pass


class Notifier(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LogNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        log.warning("ALERT to=%s subject=%s", to, subject)


class _DeadlineSocket(socket.socket):
    """A socket whose every read/write waits at most until a fixed wall-clock deadline.

    smtplib reads replies through `makefile()`, which calls `recv_into` on this object, so
    each call gets timeout = min(per-operation timeout, time left). A server trickling one
    byte at a time can therefore never stretch a send past the deadline. (Shutting the
    socket down from a timer thread is not enough on its own: some kernels and sandboxes
    don't wake a blocked reader on shutdown.)"""

    deadline: float = 0.0
    per_op: float = SEND_TIMEOUT_S

    def _arm(self) -> None:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise SendDeadlineExceeded("SMTP send exceeded its total deadline")
        super().settimeout(min(self.per_op, left))

    def recv(self, *a, **k):
        self._arm()
        return super().recv(*a, **k)

    def recv_into(self, *a, **k):
        self._arm()
        return super().recv_into(*a, **k)

    def send(self, *a, **k):
        self._arm()
        return super().send(*a, **k)

    def sendall(self, *a, **k):
        self._arm()
        return super().sendall(*a, **k)


class _DeadlineSMTP(smtplib.SMTP):
    def __init__(self, deadline: float, per_op: float):
        self._deadline, self._per_op = deadline, per_op
        # Pass the HELO name explicitly: by default smtplib calls socket.getfqdn(), a reverse
        # DNS lookup that can block for seconds (measured 2.7 s per call on a sandboxed VM).
        super().__init__(timeout=per_op, local_hostname=socket.gethostname() or "localhost")

    def _get_socket(self, host, port, timeout):
        err = None
        for family, type_, proto, _, addr in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
            sock = _DeadlineSocket(family, type_, proto)
            sock.deadline, sock.per_op = self._deadline, self._per_op
            try:
                sock._arm()
                sock.connect(addr)
                return sock
            except OSError as e:
                err = e
                sock.close()
        raise err or OSError(f"cannot connect to {host}:{port}")


class SMTPNotifier:
    def __init__(self, host: str | None = None, port: int | None = None,
                 timeout_s: float | None = None, deadline_s: float | None = None):
        self.host = host or settings.smtp_host
        self.port = port or settings.smtp_port
        self.timeout_s = timeout_s or SEND_TIMEOUT_S
        self.deadline_s = deadline_s or SEND_DEADLINE_S

    def send(self, to, subject, body):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.alert_from, to, subject
        msg.set_content(body)
        deadline = time.monotonic() + self.deadline_s
        smtp = _DeadlineSMTP(deadline, self.timeout_s)
        try:
            smtp.connect(self.host, self.port)
            smtp.send_message(msg)
            smtp.quit()
        except SendDeadlineExceeded:
            raise
        except (OSError, smtplib.SMTPException) as e:
            if time.monotonic() >= deadline:
                raise SendDeadlineExceeded(f"SMTP send exceeded {self.deadline_s}s") from e
            raise
        finally:
            try:
                smtp.close()
            except Exception:
                pass


class SESNotifier:
    def __init__(self):
        import boto3
        from botocore.config import Config
        # One HTTPS request with connect/read timeouts and a single retry. Botocore has no
        # hard total deadline, so the notify worker also renews its claim while sending.
        self.client = boto3.client("ses", config=Config(connect_timeout=5, read_timeout=SEND_TIMEOUT_S,
                                                        retries={"max_attempts": 2, "mode": "standard"}))

    def send(self, to, subject, body):
        self.client.send_email(Source=settings.alert_from, Destination={"ToAddresses": [to]},
                               Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}})


def make_notifier() -> Notifier:
    return {"smtp": SMTPNotifier, "ses": SESNotifier}.get(settings.notifier, LogNotifier)()
