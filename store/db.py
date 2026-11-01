"""Connecting to Postgres and creating the schema."""

from pathlib import Path

import psycopg

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(url: str, **kwargs) -> psycopg.Connection:
    """`url` is a libpq connection string or URL."""
    return psycopg.connect(url, **kwargs)


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text())
    conn.commit()
