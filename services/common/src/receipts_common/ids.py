"""Thread-safe deterministic document ID allocation scoped by match and kind."""

from __future__ import annotations

import threading
from collections import defaultdict

PREFIXES = {
    "event": "ev_",
    "claim": "cl_",
    "verdict": "vd_",
    "snapshot": "snap_",
    "overlay": "ov_",
    "recap": "rc_",
}


class IdAllocator:
    """Allocate reproducible, monotonic IDs within an allocator instance."""

    def __init__(self) -> None:
        self._next: dict[tuple[str, str], int] = defaultdict(lambda: 1)
        self._lock = threading.Lock()

    def allocate(self, kind: str, match_id: str) -> str:
        if kind not in PREFIXES:
            raise ValueError(f"unknown ID kind {kind!r}; expected one of {', '.join(PREFIXES)}")
        if not match_id:
            raise ValueError("match_id must be non-empty")
        with self._lock:
            key = (match_id, kind)
            number = self._next[key]
            if number > 9_999_999:
                raise OverflowError(f"ID sequence exhausted for {kind} in match {match_id}")
            self._next[key] += 1
        return f"{PREFIXES[kind]}{number:07d}"