from store import load_balances, save_balances
from store.tests.helpers import temp_schema


def test_saving_again_replaces_the_balance_and_loading_says_how_long_ago_each_was_saved():
    with temp_schema() as (conn, _):
        save_balances(conn, {"acme": 40.0, "beta": 7.5})
        save_balances(conn, {"acme": 25.0})
        conn.execute("UPDATE credit_balances SET saved_at = now() - interval '30 seconds' WHERE tenant_id = 'beta'")
        conn.commit()
        balances, away = load_balances(conn)
        assert balances == {"acme": 25.0, "beta": 7.5}
        assert 0 <= away["acme"] < 5 and 29 < away["beta"] < 35
