import os

os.environ.setdefault("ALLOW_PRIVATE_TARGETS", "false")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-32-bytes-long!!")
TEST_DB = os.environ.get("TEST_DATABASE_URL", "sqlite:///./test.db")
os.environ["DATABASE_URL"] = TEST_DB

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.db import Base, get_db, make_engine  # noqa: E402
from app.main import app  # noqa: E402

engine = make_engine(TEST_DB)
dbmod.engine = engine
TestSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def session_factory():
    return TestSession


@pytest.fixture
def client():
    def override():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth_headers(client, email="a@example.com", pw="password123"):
    r = client.post("/api/auth/register", json={"email": email, "password": pw})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
