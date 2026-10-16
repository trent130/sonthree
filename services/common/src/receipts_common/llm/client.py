"""Typed, schema-validating LLM completion client with live/record/replay modes."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import validate as contracts_validate
from jsonschema import Draft202012Validator

from ..config import Settings
from .cassette import MISSING, CassetteStore, canonical_json, request_key


class LLMError(RuntimeError):
    """Base error for completion failures."""


class CassetteNotFoundError(LLMError):
    """Raised when replay mode has no exact request cassette."""


class SchemaValidationError(LLMError):
    """Raised when a completion is not JSON matching the requested schema."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("completion does not match schema: " + "; ".join(errors))


class CompletionError(LLMError):
    """Raised after the configured number of live/record attempts."""

    def __init__(self, message: str, attempts: int, latency_ms: float) -> None:
        self.attempts = attempts
        self.latency_ms = latency_ms
        super().__init__(message)


class CompletionProvider(Protocol):
    def complete_json(
        self,
        role: str,
        model: str,
        schema: dict[str, Any],
        messages: list[dict[str, Any]],
        timeout: float,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class CallMetric:
    role: str
    attempts: int
    latency_ms: float
    success: bool


class LLMClient:
    def __init__(
        self,
        mode: Literal["live", "record", "replay"] = "replay",
        *,
        provider: CompletionProvider | None = None,
        cassette: CassetteStore | None = None,
        settings: Settings | None = None,
        models: dict[str, str] | None = None,
        max_attempts: int | None = None,
        timeout_seconds: float | None = None,
        backoff_seconds: float | None = None,
        sleep=time.sleep,
    ) -> None:
        config = settings or Settings(llm_mode=mode)
        self.mode = mode
        self.provider = provider
        self.cassette = cassette or CassetteStore(config.cassette_dir / "cassettes.jsonl")
        self.models = models or {
            "analyst": config.model_analyst,
            "narrator": config.model_narrator,
            "judge": config.model_judge,
            "translator": config.model_translator,
        }
        self.max_attempts = max_attempts if max_attempts is not None else config.llm_max_attempts
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else config.llm_timeout_seconds
        )
        self.backoff_seconds = (
            backoff_seconds if backoff_seconds is not None else config.llm_backoff_seconds
        )
        self._sleep = sleep
        self.metrics: list[CallMetric] = []
        if mode not in {"live", "record", "replay"}:
            raise ValueError(f"unsupported LLM mode {mode!r}")
        if mode in {"live", "record"} and provider is None:
            raise ValueError(f"{mode} mode requires a completion provider")
        if self.max_attempts < 1 or self.timeout_seconds <= 0 or self.backoff_seconds < 0:
            raise ValueError("attempts and timeout must be positive; backoff cannot be negative")

    def complete_json(
        self, role: str, schema: dict[str, Any], messages: list[dict[str, Any]]
    ) -> Any:
        schema_name = schema.get("$id") or schema.get("title")
        if schema_name is None:
            schema_name = hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()
        schema_name = str(schema_name)
        model = self.models.get(role, "")
        key = request_key(role, model, schema_name, messages)
        started = time.perf_counter()

        if self.mode == "replay":
            response = self.cassette.get(key)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if response is MISSING:
                self.metrics.append(CallMetric(role, 0, elapsed_ms, False))
                raise CassetteNotFoundError(f"no cassette for {role} request {key}")
            try:
                parsed = self._parse_and_validate(response, schema)
            except SchemaValidationError:
                self.metrics.append(CallMetric(role, 0, elapsed_ms, False))
                raise
            self.metrics.append(CallMetric(role, 0, elapsed_ms, True))
            return parsed

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                assert self.provider is not None
                response = self._invoke_provider(role, model, schema, messages)
                parsed = self._parse_and_validate(response, schema)
                if self.mode == "record":
                    self.cassette.put(key, parsed)
                elapsed_ms = (time.perf_counter() - started) * 1000
                self.metrics.append(CallMetric(role, attempt, elapsed_ms, True))
                return parsed
            except Exception as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    self._sleep(self.backoff_seconds * (2 ** (attempt - 1)))

        elapsed_ms = (time.perf_counter() - started) * 1000
        self.metrics.append(CallMetric(role, self.max_attempts, elapsed_ms, False))
        raise CompletionError(
            f"completion failed after {self.max_attempts} attempts: {last_error}",
            self.max_attempts,
            elapsed_ms,
        ) from last_error

    def _invoke_provider(
        self, role: str, model: str, schema: dict[str, Any], messages: list[dict[str, Any]]
    ) -> Any:
        """Enforce provider timeouts even when a provider does not implement them."""
        assert self.provider is not None
        result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def run_provider() -> None:
            try:
                result_queue.put(
                    (
                        True,
                        self.provider.complete_json(
                            role, model, schema, messages, self.timeout_seconds
                        ),
                    )
                )
            except Exception as exc:
                result_queue.put((False, exc))

        worker = threading.Thread(target=run_provider, name="receipts-llm-call", daemon=True)
        worker.start()
        try:
            succeeded, result = result_queue.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError(f"LLM provider exceeded {self.timeout_seconds} seconds") from exc
        if succeeded:
            return result
        raise result

    @staticmethod
    def _parse_and_validate(response: Any, schema: dict[str, Any]) -> Any:
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError as exc:
                raise SchemaValidationError([f"<root>: invalid JSON ({exc.msg})"]) from exc
        try:
            Draft202012Validator.check_schema(schema)
            errors = sorted(
                Draft202012Validator(
                    schema, registry=contracts_validate.REGISTRY
                ).iter_errors(response),
                key=lambda error: [str(part) for part in error.absolute_path],
            )
        except Exception as exc:
            raise SchemaValidationError([f"schema: {exc}"]) from exc
        if errors:
            formatted = []
            for error in errors:
                path = "/".join(str(part) for part in error.absolute_path) or "<root>"
                formatted.append(f"{path}: {error.message}")
            raise SchemaValidationError(formatted)
        return response