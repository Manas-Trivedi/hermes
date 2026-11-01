from pricing import TaskMeta, features


def test_slack_counts_down_to_the_deadline_and_goes_negative_after_it():
    meta = TaskMeta("t", enqueued_at=100.0, deadline=160.0)
    assert features(meta, 110.0).slack == 50.0
    assert features(meta, 170.0).slack == -10.0


def test_no_deadline_means_no_slack_and_a_batch_id_means_batched():
    f = features(TaskMeta("t", enqueued_at=0.0, batch_id="b1"), 5.0)
    assert f.slack is None and f.batched and not f.user_facing


def test_waited_never_goes_negative():
    assert features(TaskMeta("t", enqueued_at=10.0), 4.0).waited == 0.0
