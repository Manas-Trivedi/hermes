"""One HTTP call to the backend, shared by every gateway.

The gateways differ in how they order and release requests, not in how they
send one, so this is kept apart from the queueing code.
"""

import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Reply:
    status: int
    retry_after: float = 0.0  # seconds, from the Retry-After header of a 429


class HttpSender:
    def __init__(self, url: str, timeout: float = 60.0):
        self._url = url
        self._timeout = timeout

    def __call__(self, request_id: str) -> Reply:
        """Send one request and return its reply. Connection failures raise."""
        req = urllib.request.Request(
            self._url, data=b"{}", method="POST", headers={"X-Request-Id": request_id}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                r.read()
                return Reply(r.status)
        except urllib.error.HTTPError as e:
            retry_after = float(e.headers.get("Retry-After") or 0) if e.code == 429 else 0.0
            return Reply(e.code, retry_after)
