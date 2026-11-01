"""Token estimate for a request, so capacity can be released in tokens as well as requests.

Providers count a request against their tokens-per-minute limit before it runs,
on its prompt plus the most it may generate, so the estimate is the prompt's
tokens plus `max_tokens`. The prompt is estimated at about 4 characters per
token, a cheap rule that is close for English and stays off the event loop's
back; it is a budget, not a count.
"""

import math

CHARS_PER_TOKEN = 4


def estimate_tokens(prompt: str, max_tokens: int) -> int:
    if max_tokens < 0:
        raise ValueError("max_tokens must not be negative")
    return math.ceil(len(prompt) / CHARS_PER_TOKEN) + max_tokens
