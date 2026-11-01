from agents import PromptSender
from agents.pr_review import PrReviewAgent, PullRequest
from agents.tests.helpers import FakeAdapter


def test_files_are_reviewed_together_as_one_batch_then_summarized_and_nobody_is_waiting():
    adapter = FakeAdapter()
    agent = PrReviewAgent(adapter, PromptSender(None), clock=lambda: 100.0)
    result = agent.run(PullRequest("pr7", ("diff a", "diff b", "diff c")))
    assert result.ok and len(result.outcomes) == 4
    *files, summary = adapter.submitted
    assert {rid for rid, _ in files} == {f"pr-review-pr7-file{i}" for i in range(3)}
    assert summary[0] == "pr-review-pr7-summary"  # it goes last, after all the files
    assert {m.batch_id for _, m in files} == {"pr7"} and summary[1].batch_id is None
    assert {m.user_facing for _, m in adapter.submitted} == {False}
    assert {m.deadline for _, m in adapter.submitted} == {400.0}  # one deadline for the whole review
