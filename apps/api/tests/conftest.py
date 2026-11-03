"""Pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "datasets" / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def synthetic_spl_bytes(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "synthetic_fakedrug_v1.xml").read_bytes()


@pytest.fixture(scope="session")
def real_lipitor_spl_bytes(fixtures_dir: Path) -> bytes:
    path = fixtures_dir / "lipitor_v8_REAL.xml"
    if not path.exists():
        pytest.skip("Real Lipitor fixture missing")
    return path.read_bytes()


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://labellens:labellens@localhost:5432/labellens_test",
    )


@pytest.fixture(scope="session")
def engine(database_url: str):
    eng = create_engine(database_url, future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except Exception as exc:
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")
    return eng


@pytest.fixture()
def db(engine) -> Session:
    import app.models.entities  # noqa: F401
    from app.db.base import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
