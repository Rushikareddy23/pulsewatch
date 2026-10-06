"""Fill a local database with a demo account and 24h of SAMPLE check history,
so the UI has something to show before the worker has run for a day.
Login: demo@pulsewatch.dev / demo-password   (local development only)"""
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Check, Incident, Monitor, User  # noqa: E402
from app.security import hash_password  # noqa: E402

random.seed(7)
Base.metadata.create_all(engine)
now = datetime.now(timezone.utc)
with SessionLocal() as db:
    old = db.query(User).filter_by(email="demo@pulsewatch.dev").first()
    if old:
        db.delete(old); db.commit()
    u = User(email="demo@pulsewatch.dev", password_hash=hash_password("demo-password"))
    db.add(u); db.flush()
    specs = [("Portfolio site", "https://example.com/", 120, None),
             ("Payments API", "https://api.example.com/health", 85, (now - timedelta(hours=6), 23)),
             ("Docs", "https://docs.example.com/", 240, None)]
    for name, url, base, outage in specs:
        m = Monitor(user_id=u.id, name=name, url=url, interval_s=300, status="up",
                    next_check_at=now + timedelta(days=365), last_checked_at=now)
        db.add(m); db.flush()
        t = now - timedelta(hours=24)
        while t <= now:
            down = outage and outage[0] <= t < outage[0] + timedelta(minutes=outage[1])
            db.add(Check(monitor_id=m.id, checked_at=t, ok=not down, status_code=503 if down else 200,
                         latency_ms=None if down else round(random.lognormvariate(0, 0.25) * base, 1),
                         error="expected 200, got 503" if down else None))
            t += timedelta(minutes=5)
        if outage:
            db.add(Incident(monitor_id=m.id, started_at=outage[0], cause="expected 200, got 503",
                            resolved_at=outage[0] + timedelta(minutes=outage[1])))
    db.commit()
print("Seeded demo@pulsewatch.dev / demo-password")
