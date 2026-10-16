"""Append-only document store protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

STORE_KINDS = frozenset(
    {"events", "snapshots", "claims", "verdicts", "overlays", "matchstate", "recaps", "profiles"}
)


@dataclass(frozen=True, slots=True)
class StoredClaimRevision:
    claim_id: str
    revision: int
    doc: dict[str, Any]


class DocumentStore(Protocol):
    def append(self, kind: str, doc: dict[str, Any]) -> Any: ...

    def list_documents(self, kind: str, match_id: str | None = None) -> list[dict[str, Any]]: ...

    def latest_verdict(self, claim_id: str) -> dict[str, Any] | None: ...

    def eligible_claims(self, match_id: str, as_of_seq: int) -> list[dict[str, Any]]: ...