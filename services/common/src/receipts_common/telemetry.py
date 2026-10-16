"""OpenTelemetry stage spans with a console exporter for local operation."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_tracer = None


def configure_telemetry(
    exporter: str = "console", *, provider: TracerProvider | None = None
) -> TracerProvider:
    """Configure local console export, or accept a caller-provided OTel provider."""
    global _tracer
    if exporter != "console":
        raise ValueError("only the local console exporter is included in tasks 1–5")
    if provider is None:
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    _tracer = provider.get_tracer("receipts.foundation")
    return provider


def _get_tracer():
    global _tracer
    if _tracer is None:
        configure_telemetry()
    return _tracer


@contextmanager
def stage_span(
    stage: str,
    *,
    match_id: str | None = None,
    claim_id: str | None = None,
    overlay_id: str | None = None,
) -> Iterator[trace.Span]:
    """Emit a stage span carrying identifiers and measured wall duration."""
    if stage not in {"interpret", "explain", "verify", "render"}:
        raise ValueError(f"unknown pipeline stage {stage!r}")
    started = time.perf_counter()
    with _get_tracer().start_as_current_span(stage) as span:
        for name, value in (
            ("match_id", match_id),
            ("claim_id", claim_id),
            ("overlay_id", overlay_id),
        ):
            if value is not None:
                span.set_attribute(name, value)
        try:
            yield span
        finally:
            span.set_attribute("duration_ms", (time.perf_counter() - started) * 1000)