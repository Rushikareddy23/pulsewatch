"""Migrations must build the same schema as the models, on an EMPTY database
(tests use create_all on a different database, so the two never collide)."""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]
PG = os.environ.get("TEST_DATABASE_URL", "")


def _alembic(url: str):
    env = {**os.environ, "DATABASE_URL": url}
    for cmd in (["upgrade", "head"], ["check"], ["downgrade", "base"], ["upgrade", "head"]):
        r = subprocess.run([sys.executable, "-m", "alembic", *cmd], cwd=BACKEND, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, f"alembic {' '.join(cmd)} failed:\n{r.stdout}\n{r.stderr}"


def test_migrations_on_empty_sqlite(tmp_path):
    _alembic(f"sqlite:///{tmp_path / 'fresh.db'}")


@pytest.mark.skipif("postgresql" not in PG, reason="needs PostgreSQL")
def test_migrations_on_empty_postgres():
    name = f"migr_{uuid.uuid4().hex[:8]}"
    admin = create_engine(PG, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = PG.rsplit("/", 1)[0] + f"/{name}"
    try:
        _alembic(url)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
