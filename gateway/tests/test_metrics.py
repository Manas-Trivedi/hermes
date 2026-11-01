from gateway.metrics import Metrics


def ev(kind, tenant="acme", **fields):
    return {"event": kind, "gateway": "exchange", "request_id": "r", "t": 0.0, "attempt": 0, "tenant_id": tenant, **fields}


def test_counters_follow_the_events_per_tenant_and_the_page_is_prometheus_text():
    m = Metrics()
    for e in [ev("request"), ev("request"), ev("request", "beta"), ev("fill", paid=40), ev("fill", paid=55), ev("rejected"),
              ev("cancelled", "beta"), ev("result", status=200), ev("result", status=None), ev("bid", offered=3)]:
        m(e)
    text = m.render({"acme": 2}, {"acme": 12.5, "beta": 600.0}, 0.5, 1, False)
    lines = set(text.splitlines())
    assert 'hermes_requests_total{tenant="acme"} 2' in lines and 'hermes_requests_total{tenant="beta"} 1' in lines
    assert 'hermes_fills_total{tenant="acme"} 2' in lines and "hermes_last_clearing_price 55" in lines
    assert 'hermes_rejections_total{tenant="acme"} 1' in lines and 'hermes_cancelled_total{tenant="beta"} 1' in lines
    assert 'hermes_results_total{status="200",tenant="acme"} 1' in lines and 'hermes_results_total{status="0",tenant="acme"} 1' in lines
    assert 'hermes_queue_depth{tenant="acme"} 2' in lines and 'hermes_credit_balance{tenant="acme"} 12.5' in lines
    assert "hermes_rate_scale 0.5" in lines and "hermes_balance_save_failures_total 1" in lines and "hermes_event_writer_failed 0" in lines
    assert "# TYPE hermes_fills_total counter" in lines and "# TYPE hermes_queue_depth gauge" in lines


def test_a_tenant_name_cannot_break_the_page_and_no_price_is_reported_before_the_first_fill():
    text = Metrics().render({'we"ird\\\n': 1}, {}, 1.0, 0, True)
    assert 'hermes_queue_depth{tenant="we\\"ird\\\\\\n"} 1' in text.splitlines()
    assert "hermes_last_clearing_price" not in text and "hermes_event_writer_failed 1" in text
