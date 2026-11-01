from agents import PromptSender
from agents.support import SupportAgent, Ticket
from agents.tests.helpers import FakeAdapter


def test_ticket_is_triaged_then_answered_by_a_user_facing_agent_with_one_tight_deadline():
    adapter = FakeAdapter()
    agent = SupportAgent(adapter, PromptSender(None), clock=lambda: 100.0)
    assert agent.run(Ticket("t3", "my invoice is wrong")).ok
    assert [rid for rid, _ in adapter.submitted] == ["support-t3-triage", "support-t3-answer"]
    assert {m.user_facing for _, m in adapter.submitted} == {True}
    assert {m.deadline for _, m in adapter.submitted} == {120.0}
    assert {m.batch_id for _, m in adapter.submitted} == {None}
