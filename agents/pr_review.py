"""Agent A: drafts a review of a pull request.

One call per changed file, all at once and sharing the PR as their batch, then
one call that summarizes them into the review. Nobody is waiting on the draft
and a reviewer will get to it in minutes, so the deadline is loose.
"""

from dataclasses import dataclass

from agents.base import Agent, ItemResult


@dataclass(frozen=True)
class PullRequest:
    id: str
    files: tuple[str, ...]  # the diff of each changed file


class PrReviewAgent(Agent):
    name = "pr-review"
    user_facing = False
    deadline_in = 300.0

    def run(self, pr: PullRequest) -> ItemResult:
        files = [(f"{pr.id}-file{i}", f"Review this change and list any problems:\n{diff}") for i, diff in enumerate(pr.files)]
        summary = [(f"{pr.id}-summary", f"Write one review for pull request {pr.id} from the per-file findings.")]
        return self._run_stages(pr.id, [(files, pr.id), (summary, None)])
