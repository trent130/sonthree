"""JSONL cassette persistence keyed by canonical completion requests."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

MISSING = object()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_key(role: str, model: str, schema_name: str, messages: list[dict[str, Any]]) -> str:
    material = canonical_json(
        {"role": role, "model": model, "schema_name": schema_name, "messages": messages}
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class CassetteStore:
    """Append-only JSONL cassette file; the latest matching entry is replayed."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        if not self.path.exists():
            return MISSING
        found = MISSING
        with self._lock, self.path.open(encoding="utf-8") as cassette_file:
            for line_number, line in enumerate(cassette_file, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid cassette JSON at line {line_number}") from exc
                if entry.get("key") == key:
                    found = entry["response"]
        return found

    def put(self, key: str, response: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = canonical_json({"key": key, "response": response}) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as cassette_file:
            cassette_file.write(line)