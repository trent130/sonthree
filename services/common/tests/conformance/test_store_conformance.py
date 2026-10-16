"""Shared append-only and eligibility behavior suite for Store implementations."""

import copy
import json
from pathlib import Path

import pytest
import validate

from receipts_common.store import MemoryStore

ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = ROOT / "contracts" / "examples" / "valid"


def read_json(filename):
    return json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))


@pytest.fixture
def populated_store():
    store = MemoryStore()
    claims = read_json("claims.json")
    verdicts = read_json("verdicts.json")
    for claim in claims:
        store.append("claims", claim)
    for verdict in verdicts:
        store.append("verdicts", verdict)
    return store, claims, verdicts


def test_claim_revision_is_append_only_and_only_adds_renderings(populated_store):
    store, claims, _ = populated_store
    original = claims[0]
    revision = copy.deepcopy(original)
    revision["renderings"].append(
        {
            "lang": "fr",
            "text": "Une chance précoce.",
            "origin": "translated",
            "human_reviewed": False,
        }
    )

    stored = store.append("claims", revision)
    history = store.claim_revisions(original["claim_id"])

    assert stored.revision == 2
    assert len(history) == 2
    assert store.list_documents("claims")[0]["renderings"] == revision["renderings"]

    changed_assertion = copy.deepcopy(revision)
    changed_assertion["salience"] -= 0.1
    with pytest.raises(ValueError, match="renderings only"):
        store.append("claims", changed_assertion)


def test_latest_verdict_and_eligible_claims_match_frozen_contract_rules(populated_store):
    store, claims, verdicts = populated_store
    assert store.latest_verdict("cl_0000005")["attempt"] == 2
    assert store.eligible_claims("ngt-ald-demo01", 15) == validate.eligible_claims(
        claims, verdicts, 15
    )
