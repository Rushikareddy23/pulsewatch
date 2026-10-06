from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Check, Incident, Monitor, User
from ..stats import downsample
from ..schemas import CheckOut, IncidentOut, MonitorIn, MonitorOut, MonitorPatch, Stats
from ..security import current_user
from ..stats import monitor_stats
from ..url_safety import UnsafeURL, validate_target

router = APIRouter(prefix="/monitors", tags=["monitors"])
MAX_MONITORS_PER_USER = 50


def _owned(db: Session, user: User, monitor_id: int) -> Monitor:
    m = db.get(Monitor, monitor_id)
    # 404 (not 403) for other users' monitors so IDs can't be probed.
    if m is None or m.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Monitor not found")
    return m


@router.get("", response_model=list[MonitorOut])
def list_monitors(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Monitor).where(Monitor.user_id == user.id).order_by(Monitor.id)).all()


@router.post("", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
def create_monitor(body: MonitorIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        url = validate_target(str(body.url), settings.allow_private_targets)
    except UnsafeURL as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    if len(user.monitors) >= MAX_MONITORS_PER_USER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Limit of {MAX_MONITORS_PER_USER} monitors reached")
    m = Monitor(user_id=user.id, name=body.name, url=url, method=body.method,
                interval_s=max(body.interval_s, settings.min_interval_s), timeout_s=body.timeout_s,
                expected_status=body.expected_status, next_check_at=datetime.now(timezone.utc))
    db.add(m)
    db.commit()
    return m


@router.get("/{monitor_id}", response_model=MonitorOut)
def get_monitor(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _owned(db, user, monitor_id)


@router.patch("/{monitor_id}", response_model=MonitorOut)
def update_monitor(monitor_id: int, body: MonitorPatch, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    m = _owned(db, user, monitor_id)
    was_active = m.is_active
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    if was_active and body.is_active is False:
        # Paused: stop showing up/down. Any open incident stays open and is closed by the
        # next successful check after resuming (incidents are tracked independently).
        m.status, m.consecutive_failures = "pending", 0
    elif not was_active and body.is_active:
        m.next_check_at = datetime.now(timezone.utc)  # check immediately on resume
    db.commit()
    return m


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, user, monitor_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{monitor_id}/checks", response_model=list[CheckOut])
def list_checks(monitor_id: int, hours: int = Query(24, ge=1, le=720),
                max_points: int = Query(500, ge=10, le=2000), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    """Whole requested window, downsampled into at most `max_points` time buckets so long
    ranges (7 days at 1-minute checks = 10,080 rows) never drop the newest data."""
    _owned(db, user, monitor_id)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    rows = db.execute(select(Check.checked_at, Check.ok, Check.status_code, Check.latency_ms, Check.error)
                      .where(Check.monitor_id == monitor_id, Check.checked_at >= since)
                      .order_by(Check.checked_at)).all()
    return downsample(rows, since, now, max_points)


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
def list_incidents(monitor_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _owned(db, user, monitor_id)
    return db.scalars(select(Incident).where(Incident.monitor_id == monitor_id)
                      .order_by(Incident.started_at.desc()).limit(100)).all()


@router.get("/{monitor_id}/stats", response_model=Stats)
def stats(monitor_id: int, hours: int = Query(24, ge=1, le=720), user: User = Depends(current_user),
          db: Session = Depends(get_db)):
    _owned(db, user, monitor_id)
    return monitor_stats(db, monitor_id, hours)
