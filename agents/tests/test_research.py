from agents import PromptSender
from agents.research import ResearchAgent, ResearchTask
from agents.tests.helpers import FakeAdapter


def test_every_paper_is_read_in_one_batch_before_the_synthesis_and_the_deadline_is_in_between():
    adapter = FakeAdapter()
    agent = ResearchAgent(adapter, PromptSender(None), clock=lambda: 100.0)
    assert agent.run(ResearchTask("q2", "how does X work", tuple(f"paper {i}" for i in range(5)))).ok
    *papers, synthesis = adapter.submitted
    assert len(papers) == 5 and synthesis[0] == "research-q2-synthesis"
    assert {m.batch_id for _, m in papers} == {"q2"} and synthesis[1].batch_id is None
    assert {m.user_facing for _, m in adapter.submitted} == {False}
    assert {m.deadline for _, m in adapter.submitted} == {220.0}
