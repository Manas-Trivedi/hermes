"""Agent B: triages a support ticket, then answers it.

Two calls in a row, because the answer depends on the triage. A customer is
waiting, so the call is user facing and the deadline is tight. The deadline is
set from the moment the ticket arrives, so a slow triage leaves the answer less
time and its bid rises.
"""

from dataclasses import dataclass

from agents.base import Agent, ItemResult


@dataclass(frozen=True)
class Ticket:
    id: str
    text: str


class SupportAgent(Agent):
    name = "support"
    user_facing = True
    deadline_in = 20.0

    def run(self, ticket: Ticket) -> ItemResult:
        triage = [(f"{ticket.id}-triage", f"Classify this support ticket and rate how severe it is:\n{ticket.text}")]
        answer = [(f"{ticket.id}-answer", f"Draft a reply to this support ticket, using its classification:\n{ticket.text}")]
        return self._run_stages(ticket.id, [(triage, None), (answer, None)])
