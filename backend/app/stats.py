from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Check, Incident


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (same definition as PostgreSQL percentile_cont)."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def monitor_stats(db: Session, monitor_id: int, hours: int) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.execute(select(Check.ok, Check.latency_ms)
                      .where(Check.monitor_id == monitor_id, Check.checked_at >= since)).all()
    lat = [r.latency_ms for r in rows if r.ok and r.latency_ms is not None]
    incidents = db.scalar(select(func.count()).select_from(Incident)
                          .where(Incident.monitor_id == monitor_id, Incident.started_at >= since))
    return {
        "hours": hours,
        "checks": len(rows),
        "uptime_pct": round(100 * sum(r.ok for r in rows) / len(rows), 3) if rows else None,
        "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else None,
        "p95_latency_ms": round(percentile(lat, 0.95), 1) if lat else None,
        "incidents": incidents or 0,
    }


def downsample(rows, since: datetime, until: datetime, max_points: int) -> list[dict]:
    """Return raw checks if they fit, otherwise one point per time bucket:
    ok only if every check in the bucket passed, latency = mean of successful checks."""
    if len(rows) <= max_points:
        return [dict(checked_at=r.checked_at, ok=r.ok, status_code=r.status_code,
                     latency_ms=r.latency_ms, error=r.error) for r in rows]
    width = (until - since).total_seconds() / max_points
    buckets: dict[int, list] = {}
    for r in rows:
        t = r.checked_at if r.checked_at.tzinfo else r.checked_at.replace(tzinfo=timezone.utc)
        idx = min(int((t - since).total_seconds() // width), max_points - 1)
        buckets.setdefault(idx, []).append(r)
    out = []
    for idx in sorted(buckets):
        b = buckets[idx]
        lat = [r.latency_ms for r in b if r.ok and r.latency_ms is not None]
        failed = sum(not r.ok for r in b)
        out.append(dict(checked_at=b[-1].checked_at, ok=failed == 0,
                        status_code=b[-1].status_code,
                        latency_ms=round(sum(lat) / len(lat), 1) if lat else None,
                        error=f"{failed} of {len(b)} checks failed" if failed else None))
    return out
