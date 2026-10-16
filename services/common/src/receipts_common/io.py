"""Contract validation at bus and store boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import validate as contracts_validate

VALIDATORS = {
    "events": contracts_validate.validate_event,
    "snapshots": contracts_validate.validate_snapshot,
    "claims": contracts_validate.validate_claim,
    "verdicts": contracts_validate.validate_verdict,
    "overlays": contracts_validate.validate_overlay,
    "matchstate": contracts_validate.validate_match_state,
    "recaps": contracts_validate.validate_recap,
    "profiles": contracts_validate.validate_profile,
    "eval-label": contracts_validate.validate_eval_label,
    "eval-manifest": contracts_validate.validate_eval_manifest,
}


class ContractViolation(ValueError):
    """An invalid document, including its contract topic and first field path."""

    def __init__(self, topic: str, errors: list[str]) -> None:
        self.topic = topic
        self.errors = tuple(errors)
        first = errors[0] if errors else "<root>: invalid document"
        self.path = first.split(":", maxsplit=1)[0]
        super().__init__(f"{topic} document violates contract at {self.path}: {first}")


def validate_document(topic: str, doc: dict[str, Any]) -> None:
    validator = VALIDATORS.get(topic)
    if validator is None:
        raise ValueError(f"no contract validator registered for {topic!r}")
    errors = validator(doc)
    if errors:
        raise ContractViolation(topic, errors)


class BusWriter(Protocol):
    def publish(self, topic: str, key: str, doc: dict[str, Any]) -> Any: ...


class StoreWriter(Protocol):
    def append(self, kind: str, doc: dict[str, Any]) -> Any: ...


class ValidatingWriter:
    """Validate each document before forwarding it to its destination."""

    def publish(self, bus: BusWriter, topic: str, key: str, doc: dict[str, Any]) -> Any:
        validate_document(topic, doc)
        return bus.publish(topic, key, doc)

    def append(self, store: StoreWriter, kind: str, doc: dict[str, Any]) -> Any:
        validate_document(kind, doc)
        return store.append(kind, doc)


@dataclass(frozen=True, slots=True)
class DeadLetterRecord:
    topic: str
    key: str
    offset: int
    doc: dict[str, Any]
    errors: tuple[str, ...]


class Subscription(Protocol):
    def poll(self, timeout: float | None = None) -> Any: ...

    def commit(self, offset: int) -> None: ...


@dataclass(slots=True)
class ValidatingReader:
    """Validate bus records and retain invalid records as dead letters."""

    subscription: Subscription
    topic: str
    dead_letters: list[DeadLetterRecord] = field(default_factory=list)

    def read(self, timeout: float | None = None) -> Any | None:
        """Return the next valid record; poison records are recorded and committed."""
        while True:
            record = self.subscription.poll(timeout)
            if record is None:
                return None
            try:
                validate_document(self.topic, record.doc)
            except ContractViolation as exc:
                self.dead_letters.append(
                    DeadLetterRecord(
                        topic=self.topic,
                        key=record.key,
                        offset=record.offset,
                        doc=record.doc,
                        errors=exc.errors,
                    )
                )
                self.subscription.commit(record.offset)
                continue
            return record