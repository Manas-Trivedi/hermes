"""Saving and loading tenants' credit balances (pricing.Budgets.snapshot and restore)."""


def save_balances(conn, balances: dict[str, float]) -> None:
    with conn.transaction():
        for tenant_id, balance in balances.items():
            conn.execute(
                "INSERT INTO credit_balances (tenant_id, balance, saved_at) VALUES (%s, %s, now())"
                " ON CONFLICT (tenant_id) DO UPDATE SET balance = EXCLUDED.balance, saved_at = EXCLUDED.saved_at",
                (tenant_id, balance),
            )


def load_balances(conn) -> tuple[dict[str, float], dict[str, float]]:
    """The saved balances, and for each the seconds since it was saved (by the database's clock)."""
    rows = conn.execute("SELECT tenant_id, balance, extract(epoch FROM now() - saved_at) FROM credit_balances").fetchall()
    conn.commit()
    return {t: b for t, b, _ in rows}, {t: float(s) for t, _, s in rows}
