"""Deterministic provider fake for local end-to-end tests."""

from __future__ import annotations

from collections import deque
from typing import Any


class FakeLiveProvider:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, role, model, schema, messages, timeout):
        self.calls.append(
            {
                "role": role,
                "model": model,
                "schema": schema,
                "messages": messages,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise RuntimeError("fake provider has no queued response")
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response