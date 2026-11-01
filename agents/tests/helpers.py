import threading


class FakeTask:
    def __init__(self, request_id):
        self.request_id = request_id
        self.status = None
        self.attempts = 0
        self.cancelled = False
        self.error = None
        self._done = threading.Event()

    def wait(self, timeout=None):
        return self._done.wait(timeout)

    def finish(self, status=200):
        self.status, self.attempts = status, 1
        self._done.set()


class FakeAdapter:
    """Completes every call at once unless told to hold them. Records what it was given."""

    def __init__(self, hold=False, can_cancel=True, status=200):
        self.hold, self.can_cancel, self.status = hold, can_cancel, status
        self.submitted: list[tuple[str, object]] = []  # (request_id, meta), in arrival order
        self.tasks: list[FakeTask] = []
        self.cancelled: list[FakeTask] = []
        self._lock = threading.Lock()

    def submit(self, request_id, meta):
        task = FakeTask(request_id)
        with self._lock:
            self.submitted.append((request_id, meta))
            self.tasks.append(task)
        if not self.hold:
            task.finish(self.status)
        return task

    def cancel(self, task):
        self.cancelled.append(task)
        if self.can_cancel:
            task.cancelled = True
            task._done.set()
        return self.can_cancel
