"""
Root pytest conftest.py — provides the `db` session fixture for all backend tests.

Uses an in-memory SQLite database so tests run in isolation without requiring
Docker/PostgreSQL. Each test gets a fresh rolled-back session.
"""
import os

# Fast unit tests: avoid downloading multi-GB sentence-transformers weights unless overridden.
os.environ.setdefault("TEXT_EMBEDDING_PROVIDER", "mock")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.config import get_settings
from app.services.text_embedding_provider_factory import clear_text_embedding_provider_cache_for_tests

import app.models  # noqa: F401 — loads ORM + registers text_embedding_listeners

get_settings.cache_clear()
clear_text_embedding_provider_cache_for_tests()

# SQLite in-memory for speed. For full PG compatibility test separately.
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Enable FK enforcement in SQLite (off by default)
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once per test session."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """
    Provide a transactional database session for each test.
    Changes are rolled back after each test, keeping tests isolated.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()
