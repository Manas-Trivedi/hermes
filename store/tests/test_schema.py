import psycopg
import pytest

from store import apply_schema
from store.tests.helpers import temp_schema


def seed_request(conn):
    run_id = conn.execute("INSERT INTO experiment_runs (name, condition) VALUES ('r', 'exchange') RETURNING id").fetchone()[0]
    conn.execute("INSERT INTO requests (run_id, request_id, gateway, t_request) VALUES (%s, 'a', 'exchange', 0)", (run_id,))
    conn.commit()
    return run_id


def test_apply_twice_keeps_data():
    with temp_schema() as conn:
        seed_request(conn)
        apply_schema(conn)
        assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 1


def test_orders_and_fills_need_a_known_request():
    with temp_schema() as conn:
        run_id = seed_request(conn)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("INSERT INTO fills (run_id, request_id, attempt, paid, offered, t) VALUES (%s, 'nope', 0, 1, 1, 0)", (run_id,))
        conn.rollback()
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("INSERT INTO orders (run_id, request_id, attempt, kind, offered, t) VALUES (%s, 'nope', 0, 'bid', 1, 0)", (run_id,))


def test_deleting_a_run_removes_its_rows():
    with temp_schema() as conn:
        run_id = seed_request(conn)
        conn.execute("INSERT INTO orders (run_id, request_id, attempt, kind, offered, t) VALUES (%s, 'a', 0, 'bid', 5, 0)", (run_id,))
        conn.execute("DELETE FROM experiment_runs WHERE id = %s", (run_id,))
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
