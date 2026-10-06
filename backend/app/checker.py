import asyncio
import time
from dataclasses import dataclass

import httpx

from .config import settings
from .url_safety import UnsafeURL, resolve_target


@dataclass(frozen=True)
class Target:
    monitor_id: int
    url: str
    method: str
    timeout_s: float
    expected_status: int


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None


async def check(client: httpx.AsyncClient, t: Target, allow_private: bool | None = None) -> CheckResult:
    allow = settings.allow_private_targets if allow_private is None else allow_private
    try:
        # Resolve once and validate every address...
        rt = await asyncio.to_thread(resolve_target, t.url, allow)
    except UnsafeURL as e:
        return CheckResult(False, None, None, f"blocked: {e}")
    start = time.perf_counter()
    try:
        # ...then connect to exactly that IP. Host header + SNI keep virtual hosting and
        # certificate verification working against the real hostname.
        r = await client.request(
            t.method, rt.connect_url, timeout=t.timeout_s, follow_redirects=False,
            headers={"Host": urlhost(t.url)}, extensions={"sni_hostname": rt.host})
        latency = (time.perf_counter() - start) * 1000
        ok = r.status_code == t.expected_status
        return CheckResult(ok, r.status_code, round(latency, 1),
                           None if ok else f"expected {t.expected_status}, got {r.status_code}")
    except httpx.TimeoutException:
        return CheckResult(False, None, None, f"timeout after {t.timeout_s}s")
    except httpx.HTTPError as e:
        return CheckResult(False, None, None, f"{type(e).__name__}: {e}"[:500])


def urlhost(url: str) -> str:
    """Host header value, including a non-default port."""
    u = httpx.URL(url)
    default = {"http": 80, "https": 443}[u.scheme]
    return u.host if u.port in (None, default) else f"{u.host}:{u.port}"
