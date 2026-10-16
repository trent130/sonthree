"""Thread-safe in-process append-only event log with consumer-group offsets."""

from __future__ import annotations

import copy
import threading
import time
from collections import defaultdict
from typing import Any

from .base import BUS_TOPICS, BusRecord


class LocalEventBus:
    """An in-memory log; records for every key retain global topic publish order."""

    def __init__(self) -> None:
        self._records: dict[str, list[BusRecord]] = defaultdict(list)
        self._committed: dict[tuple[str, str], int] = {}
        self._condition = threading.Condition()

    def publish(self, topic: str, key: str, doc: dict[str, Any]) -> BusRecord:
        if topic not in BUS_TOPICS:
            raise ValueError(f"unsupported topic {topic!r}")
        if not key:
            raise ValueError("record key must be non-empty")
        with self._condition:
            record = BusRecord(topic, key, len(self._records[topic]), copy.deepcopy(doc))
            self._records[topic].append(record)
            self._condition.notify_all()
            return copy.deepcopy(record)

    def subscribe(self, topic: str, group: str, from_offset: int = 0) -> LocalSubscription:
        if topic not in BUS_TOPICS:
            raise ValueError(f"unsupported topic {topic!r}")
        if not group:
            raise ValueError("consumer group must be non-empty")
        if from_offset < 0:
            raise ValueError("from_offset cannot be negative")
        with self._condition:
            committed = self._committed.get((topic, group))
            cursor = committed + 1 if committed is not None else from_offset
        return LocalSubscription(self, topic, group, cursor)

    def records(self, topic: str) -> list[BusRecord]:
        """Return a defensive snapshot of a topic log, useful for diagnostics/tests."""
        with self._condition:
            return copy.deepcopy(self._records[topic])


class LocalSubscription:
    def __init__(self, bus: LocalEventBus, topic: str, group: str, cursor: int) -> None:
        self._bus = bus
        self.topic = topic
        self.group = group
        self._cursor = cursor
        self._last_delivered = cursor - 1

    def poll(self, timeout: float | None = None) -> BusRecord | None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._bus._condition:
            while self._cursor >= len(self._bus._records[self.topic]):
                if timeout == 0:
                    return None
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._bus._condition.wait(remaining)
            record = self._bus._records[self.topic][self._cursor]
            self._last_delivered = self._cursor
            self._cursor += 1
            return copy.deepcopy(record)

    def commit(self, offset: int) -> None:
        with self._bus._condition:
            current = self._bus._committed.get((self.topic, self.group), -1)
            if offset <= current:
                return
            if offset > self._last_delivered:
                raise ValueError("cannot commit an offset that has not been delivered")
            self._bus._committed[(self.topic, self.group)] = offset
