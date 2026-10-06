from conftest import auth_headers


def test_register_login_me(client):
    h = auth_headers(client)
    assert client.get("/api/auth/me", headers=h).json()["email"] == "a@example.com"
    r = client.post("/api/auth/login", json={"email": "A@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["access_token"]


def test_duplicate_email_rejected(client):
    auth_headers(client)
    r = client.post("/api/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert r.status_code == 409


def test_wrong_password_and_unknown_user_look_identical(client):
    auth_headers(client)
    a = client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrongpass1"})
    b = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrongpass1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_requires_token(client):
    assert client.get("/api/monitors").status_code == 401
    assert client.get("/api/monitors", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_short_password_rejected(client):
    assert client.post("/api/auth/register", json={"email": "b@example.com", "password": "short"}).status_code == 422


def test_password_over_72_bytes_is_a_clean_422_not_500(client):
    r = client.post("/api/auth/register", json={"email": "c@example.com", "password": "a" * 73})
    assert r.status_code == 422 and "72 bytes" in r.text
    r = client.post("/api/auth/register", json={"email": "d@example.com", "password": "é" * 37})  # 74 bytes
    assert r.status_code == 422
    assert client.post("/api/auth/register", json={"email": "e@example.com", "password": "a" * 72}).status_code == 201
