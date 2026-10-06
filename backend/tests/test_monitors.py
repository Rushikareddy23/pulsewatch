import pytest

from conftest import auth_headers


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr("app.url_safety.resolve_host", lambda h: ["93.184.215.14"])


def make(client, h, **kw):
    body = {"name": "Example", "url": "https://example.com/", **kw}
    return client.post("/api/monitors", json=body, headers=h)


def test_crud_flow(client):
    h = auth_headers(client)
    r = make(client, h, interval_s=60)
    assert r.status_code == 201
    mid = r.json()["id"]
    assert r.json()["status"] == "pending"
    assert [m["id"] for m in client.get("/api/monitors", headers=h).json()] == [mid]
    r = client.patch(f"/api/monitors/{mid}", json={"name": "Renamed", "interval_s": 120}, headers=h)
    assert r.json()["name"] == "Renamed" and r.json()["interval_s"] == 120
    assert client.delete(f"/api/monitors/{mid}", headers=h).status_code == 204
    assert client.get(f"/api/monitors/{mid}", headers=h).status_code == 404


def test_users_cannot_see_each_others_monitors(client):
    alice = auth_headers(client, "alice@example.com")
    bob = auth_headers(client, "bob@example.com")
    mid = make(client, alice).json()["id"]
    assert client.get("/api/monitors", headers=bob).json() == []
    for method, path in [("get", ""), ("delete", ""), ("get", "/checks"), ("get", "/stats"), ("get", "/incidents")]:
        assert getattr(client, method)(f"/api/monitors/{mid}{path}", headers=bob).status_code == 404
    assert client.patch(f"/api/monitors/{mid}", json={"name": "x"}, headers=bob).status_code == 404


def test_rejects_internal_target(client, monkeypatch):
    h = auth_headers(client)
    r = make(client, h, url="http://169.254.169.254/latest/meta-data/")
    assert r.status_code == 422


def test_validation(client):
    h = auth_headers(client)
    assert make(client, h, interval_s=5).status_code == 422
    assert make(client, h, url="not a url").status_code == 422
    assert make(client, h, method="POST").status_code == 422


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_checks_endpoint_downsamples_long_ranges(client, session_factory):
    from datetime import datetime, timedelta, timezone

    from app.models import Check
    h = auth_headers(client)
    mid = make(client, h).json()["id"]
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        db.add_all([Check(monitor_id=mid, checked_at=now - timedelta(minutes=i), ok=True, latency_ms=20.0)
                    for i in range(3000)])
        db.commit()
    pts = client.get(f"/api/monitors/{mid}/checks?hours=168", headers=h).json()
    assert len(pts) <= 500
    def aware(s):
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)  # SQLite drops the offset
    newest = max(aware(p["checked_at"]) for p in pts)
    assert now - newest < timedelta(minutes=30)
