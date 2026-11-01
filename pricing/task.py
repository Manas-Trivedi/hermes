"""What the urgency scorer knows about a task, and the features it reads off it.

TaskMeta is what the caller declares when a task is created. It is immutable, so
a task can be re-scored later (aging) from the same facts. Features are the raw
numbers the scorer turns into price; they depend on the time of scoring.

Every time here is seconds on one clock (the gateways use time.monotonic), so
`deadline` is an absolute time on that clock, not a duration.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskMeta:
    tenant_id: str  # who the task belongs to; carried for budgets and auth (4.5, 9.3), not scored
    enqueued_at: float
    deadline: float | None = None  # when the result is needed by; None if nobody is waiting on a time
    user_facing: bool = False  # a person is waiting on the answer
    batch_id: str | None = None  # set if the task is one call of a bulk job
    agent_id: str | None = None  # which agent's credit budget pays for the task (4.5)


@dataclass(frozen=True)
class Features:
    user_facing: bool
    batched: bool
    slack: float | None  # seconds left to the deadline, negative once it has passed; None without a deadline
    waited: float  # seconds since the task was enqueued


def features(meta: TaskMeta, now: float) -> Features:
    return Features(
        user_facing=meta.user_facing,
        batched=meta.batch_id is not None,
        slack=None if meta.deadline is None else meta.deadline - now,
        waited=max(0.0, now - meta.enqueued_at),
    )
