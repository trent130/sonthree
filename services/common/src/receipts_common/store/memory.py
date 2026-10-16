"""Append-only in-memory document store."""

from __future__ import annotations

import copy
import threading
from collections import defaultdict
from typing import Any

import validate as contracts_validate

from ..io import validate_document
from .base import STORE_KINDS, StoredClaimRevision

_IDS = {
    "events": "event_id",
    "snapshots": "snapshot_id",
    "claims": "claim_id",
    "verdicts": "verdict_id",
    "overlays": "overlay_id",
    "recaps": "recap_id",
    "profiles": "profile_id",
}


class MemoryStore:
    """Store validated immutable documents; claim renderings may only be appended."""

    def __init__(self) -> None:
        self._docs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._by_id: dict[tuple[str, str], dict[str, Any]] = {}
        self._claim_history: dict[str, list[StoredClaimRevision]] = defaultdict(list)
        self._lock = threading.RLock()

    def append(self, kind: str, doc: dict[str, Any]) -> StoredClaimRevision | dict[str, Any]:
        if kind not in STORE_KINDS:
            raise ValueError(f"unsupported document kind {kind!r}")
        validate_document(kind, doc)
        frozen = copy.deepcopy(doc)
        with self._lock:
            if kind == "claims":
                claim_id = frozen["claim_id"]
                history = self._claim_history[claim_id]
                if history:
                    previous = history[-1].doc
                    self._validate_rendering_revision(previous, frozen)
                stored = StoredClaimRevision(claim_id, len(history) + 1, frozen)
                history.append(stored)
                if not history[:-1]:
                    self._docs[kind].append(frozen)
                else:
                    self._replace_latest_claim(claim_id, frozen)
                self._by_id[(kind, claim_id)] = frozen
                return copy.deepcopy(stored)

            identity = _IDS.get(kind)
            if identity:
                key = (kind, frozen[identity])
                if key in self._by_id:
                    raise ValueError(f"{kind} {frozen[identity]} is append-only and already exists")
                self._by_id[key] = frozen
            self._docs[kind].append(frozen)
            return copy.deepcopy(frozen)

    @staticmethod
    def _validate_rendering_revision(previous: dict[str, Any], current: dict[str, Any]) -> None:
        old_base = {key: value for key, value in previous.items() if key != "renderings"}
        new_base = {key: value for key, value in current.items() if key != "renderings"}
        if old_base != new_base:
            raise ValueError("claim revision may change renderings only")
        old_renderings = previous["renderings"]
        new_renderings = current["renderings"]
        if (
            len(new_renderings) <= len(old_renderings)
            or new_renderings[: len(old_renderings)] != old_renderings
        ):
            raise ValueError(
                "claim revision must append renderings without changing existing ones"
            )

    def _replace_latest_claim(self, claim_id: str, current: dict[str, Any]) -> None:
        for index, existing in enumerate(self._docs["claims"]):
            if existing["claim_id"] == claim_id:
                self._docs["claims"][index] = current
                return

    def list_documents(self, kind: str, match_id: str | None = None) -> list[dict[str, Any]]:
        if kind not in STORE_KINDS:
            raise ValueError(f"unsupported document kind {kind!r}")
        with self._lock:
            docs = self._docs[kind]
            if match_id is not None:
                docs = [doc for doc in docs if doc.get("match_id") == match_id]
            return copy.deepcopy(docs)

    def claim_revisions(self, claim_id: str) -> list[StoredClaimRevision]:
        with self._lock:
            return copy.deepcopy(self._claim_history.get(claim_id, []))

    def latest_verdict(self, claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            matches = [doc for doc in self._docs["verdicts"] if doc["claim_id"] == claim_id]
            if not matches:
                return None
            return copy.deepcopy(max(matches, key=lambda doc: (doc["attempt"], doc["verdict_id"])))

    def eligible_claims(self, match_id: str, as_of_seq: int) -> list[dict[str, Any]]:
        if as_of_seq < 0:
            raise ValueError("as_of_seq cannot be negative")
        with self._lock:
            claims = [doc for doc in self._docs["claims"] if doc["match_id"] == match_id]
            verdicts = [doc for doc in self._docs["verdicts"] if doc["match_id"] == match_id]
        return copy.deepcopy(contracts_validate.eligible_claims(claims, verdicts, as_of_seq))
