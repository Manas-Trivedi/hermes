"""Agent C: synthesizes a research question from a set of papers.

A burst: one call per paper, all at once and sharing the task as their batch,
then one call that synthesizes the findings. Papers arrive in sets, so this
agent sends nothing for a while and then many calls together. Nobody is waiting
on the answer, and the deadline sits between the PR reviewer's and the support
agent's.
"""

from dataclasses import dataclass

from agents.base import Agent, ItemResult


@dataclass(frozen=True)
class ResearchTask:
    id: str
    question: str
    papers: tuple[str, ...]  # the text of each paper


class ResearchAgent(Agent):
    name = "research"
    user_facing = False
    deadline_in = 120.0

    def run(self, task: ResearchTask) -> ItemResult:
        papers = [(f"{task.id}-paper{i}", f"Extract what this paper says about: {task.question}\n{text}") for i, text in enumerate(task.papers)]
        synthesis = [(f"{task.id}-synthesis", f"Synthesize an answer to: {task.question}, from the per-paper findings.")]
        return self._run_stages(task.id, [(papers, task.id), (synthesis, None)])
