"""Fixture-driven end-to-end checks across contracts, bus, store, LLM, and telemetry."""

import copy
import json
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from receipts_common.bus import BUS_TOPICS, LocalEventBus
from receipts_common.config import load_settings
from receipts_common.ids import IdAllocator
from receipts_common.io import (
    ContractViolation,
    ValidatingReader,
    ValidatingWriter,
    validate_document,
)
from receipts_common.llm import CassetteNotFoundError, CassetteStore, LLMClient
from receipts_common.llm.testing import FakeLiveProvider
from receipts_common.store import MemoryStore
from receipts_common.telemetry import configure_telemetry, stage_span

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "contracts" / "examples"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def contract_examples():
    valid = EXAMPLES / "valid"
    return {
        "events": load_jsonl(valid / "match_stream.jsonl"),
        "snapshots": load_json(valid / "snapshots.json"),
        "claims": load_json(valid / "claims.json"),
        "verdicts": load_json(valid / "verdicts.json"),
        "overlays": load_jsonl(valid / "overlays.jsonl"),
        "matchstate": [load_json(valid / "match_state.json")],
        "recaps": [load_json(valid / "recap.json")],
        "profiles": load_json(valid / "profiles.json"),
    }


def test_all_contract_fixtures_round_trip_through_validating_bus_and_store():
    settings = load_settings(
        {"MODE": "local", "LLM_MODE": "replay", "LLM_MAX_ATTEMPTS": "2"}
    )
    assert settings.mode == "local"
    assert settings.llm_mode == "replay"
    assert settings.llm_max_attempts == 2

    ids = IdAllocator()
    assert ids.allocate("event", "ngt-ald-demo01") == "ev_0000001"
    assert ids.allocate("event", "ngt-ald-demo01") == "ev_0000002"
    assert ids.allocate("event", "different-match") == "ev_0000001"

    writer = ValidatingWriter()
    bus = LocalEventBus()
    store = MemoryStore()
    fixtures = contract_examples()

    for kind, documents in fixtures.items():
        for doc in documents:
            validate_document(kind, doc)
            writer.append(store, kind, doc)
            if kind in BUS_TOPICS:
                writer.publish(bus, kind, doc["match_id"], doc)

    for kind, documents in fixtures.items():
        assert store.list_documents(kind) == documents
        if kind in BUS_TOPICS:
            reader = ValidatingReader(bus.subscribe(kind, f"fixture-{kind}"), kind)
            round_tripped = [reader.read(timeout=0).doc for _ in documents]
            assert round_tripped == documents

    eval_examples = EXAMPLES / "eval"
    for label in load_jsonl(eval_examples / "labels.jsonl"):
        validate_document("eval-label", label)
    validate_document("eval-manifest", load_json(eval_examples / "manifest.json"))


def test_invalid_fixture_is_rejected_and_reader_routes_poison_to_dead_letter():
    source = contract_examples()["claims"][0]
    mutated = copy.deepcopy(source)
    mutated["salience"] = 3
    writer = ValidatingWriter()
    bus = LocalEventBus()

    with pytest.raises(ContractViolation, match="salience"):
        writer.publish(bus, "claims", source["match_id"], mutated)

    bus.publish("claims", source["match_id"], source)
    bus.publish("claims", source["match_id"], mutated)
    reader = ValidatingReader(bus.subscribe("claims", "poison-check"), "claims")
    assert reader.read(timeout=0).doc == source
    assert reader.read(timeout=0) is None
    assert len(reader.dead_letters) == 1
    assert reader.dead_letters[0].offset == 1
    assert "salience" in " ".join(reader.dead_letters[0].errors)


def test_record_replay_retry_and_stage_span_smoke(tmp_path):
    schema = {
        "$id": "urn:test:completion",
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    messages = [{"role": "user", "content": "Return the fixture answer."}]
    cassette = CassetteStore(tmp_path / "tests" / "cassettes" / "fixture.jsonl")
    provider = FakeLiveProvider([TimeoutError("temporary"), '{"answer": 42}'])
    recorder = LLMClient(
        "record", provider=provider, cassette=cassette, max_attempts=2, backoff_seconds=0,
        sleep=lambda _: None,
    )

    assert recorder.complete_json("analyst", schema, messages) == {"answer": 42}
    assert recorder.metrics[-1].attempts == 2
    assert len(provider.calls) == 2
    assert LLMClient("replay", cassette=cassette).complete_json(
        "analyst", schema, messages
    ) == {"answer": 42}
    with pytest.raises(CassetteNotFoundError):
        LLMClient("replay", cassette=cassette).complete_json(
            "analyst", schema, [{"role": "user", "content": "missing"}]
        )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    configure_telemetry(provider=provider)
    with stage_span("verify", match_id="ngt-ald-demo01", claim_id="cl_0000001"):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["match_id"] == "ngt-ald-demo01"
    assert spans[0].attributes["claim_id"] == "cl_0000001"
    assert spans[0].attributes["duration_ms"] >= 0