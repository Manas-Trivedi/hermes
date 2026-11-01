import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest

from store import apply_schema, connect

URL = os.environ.get("HERMES_TEST_DATABASE_URL")


def require_database():
    if not URL:
        pytest.skip("HERMES_TEST_DATABASE_URL is not set")


@contextmanager
def temp_schema():
    """A connection whose tables live in a throwaway schema, dropped on exit."""
    require_database()
    name = f"t_{uuid.uuid4().hex[:12]}"
    with connect(URL, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {name}")
        try:
            with connect(URL, options=f"-c search_path={name}") as conn:
                apply_schema(conn)
                yield conn
        finally:
            admin.execute(f"DROP SCHEMA {name} CASCADE")
