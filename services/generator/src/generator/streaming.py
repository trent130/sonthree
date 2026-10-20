"""Paced local publication of generated event streams."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from receipts_common.bus.base import EventBus
from receipts_common.io import ValidatingWriter


class StreamControl:
    """Thread-safe pause/resume gate for a single event stream."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._paused = False

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def pause(self) -> None:
        with self._condition:
            self._paused = True
            self._condition.notify_all()

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def wait(self, seconds: float) -> None:
        """Wait for a duration, excluding time spent paused."""
        remaining = max(0.0, seconds)
        with self._condition:
            while True:
                while self._paused:
                    self._condition.wait()
                if remaining <= 0:
                    return
                started = time.monotonic()
                self._condition.wait(timeout=remaining)
                remaining -= max(0.0, time.monotonic() - started)


def _emitted_at() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stream_events(
    events: list[dict],
    bus: EventBus,
    *,
    speed: float = 1.0,
    from_seq: int = 1,
    control: StreamControl | None = None,
    now: Callable[[], str] = _emitted_at,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Publish events against match time; return the number successfully published."""
    if speed <= 0 or speed > 60:
        raise ValueError("speed must be greater than 0 and at most 60")
    if from_seq < 1:
        raise ValueError("from_seq must be at least 1")

    selected = (event for event in events if event["seq"] >= from_seq)
    previous_time: int | None = None
    published = 0
    writer = ValidatingWriter()
    for event in selected:
        if control is not None:
            control.wait(0)
        if previous_time is not None:
            delay = max(0.0, event["match_time_ms"] - previous_time) / 1000 / speed
            if control is None:
                sleep(delay)
            else:
                control.wait(delay)
                control.wait(0)
        stamped = copy.deepcopy(event)
        stamped["emitted_at"] = now()
        writer.publish(bus, "events", event["match_id"], stamped)
        previous_time = event["match_time_ms"]
        published += 1
    return published
