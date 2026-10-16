"""Event bus protocol and immutable record type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

BUS_TOPICS = frozenset(
    {"events", "snapshots", "claims", "verdicts", "overlays", "matchstate", "recaps"}
)


@dataclass(frozen=True, slots=True)
class BusRecord:
    topic: str
    key: str
    offset: int
    doc: dict[str, Any]


class Subscription(Protocol):
    def poll(self, timeout: float | None = None) -> BusRecord | None: ...

    def commit(self, offset: int) -> None: ...


class EventBus(Protocol):
    def publish(self, topic: str, key: str, doc: dict[str, Any]) -> BusRecord: ...

    def subscribe(self, topic: str, group: str, from_offset: int = 0) -> Subscription: ...