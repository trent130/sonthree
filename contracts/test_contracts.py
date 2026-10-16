import copy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import validate as V

EX = Path(__file__).parent / "examples" / "valid"
EVENTS = V.load_jsonl(EX / "match_stream.jsonl")
CLAIMS = json.loads((EX / "claims.json").read_text(encoding="utf-8"))
VERDICTS = json.loads((EX / "verdicts.json").read_text(encoding="utf-8"))
OVERLAYS = V.load_jsonl(EX / "overlays.jsonl")


def ev(seq):
    return copy.deepcopy(EVENTS[seq - 1])


def claim(n):
    return copy.deepcopy(CLAIMS[n - 1])


# ------------------------------------------------------------- the valid fixtures
def test_fixtures_pass_everything():
    assert V.validate_all(EVENTS, CLAIMS, VERDICTS, OVERLAYS) == []


def test_every_event_also_passes_the_root_oneof():
    root = Draft202012Validator({"$ref": V.URN + "event"}, registry=V.REGISTRY, format_checker=FormatChecker())
    for e in EVENTS:
        assert list(root.iter_errors(e)) == [], e["event_id"]


def test_every_event_type_is_covered_or_deliberately_not():
    covered = {e["type"] for e in EVENTS}
    not_in_fixture = set(V.EVENT_TYPE_TO_DEF) - covered
    assert not_in_fixture == {"foul", "card", "substitution"}


# ------------------------------------------------------------- schema-level rejections
def _drop(path_keys):
    def f(e):
        d = e
        for k in path_keys[:-1]:
            d = d[k]
        del d[path_keys[-1]]
    return f


def _set(path_keys, value):
    def f(e):
        d = e
        for k in path_keys[:-1]:
            d = d[k]
        d[path_keys[-1]] = value
    return f


EVENT_MUTATIONS = {
    "unknown top-level field": (4, _set(["extra"], 1)),
    "unknown payload field": (4, _set(["payload", "extra"], 1)),
    "pass without receiver_id key": (4, _drop(["payload", "receiver_id"])),
    "pass without possession_id": (4, _drop(["possession_id"])),
    "pass without player_id": (4, _drop(["player_id"])),
    "shot xg above 1": (15, _set(["payload", "xg"], 1.4)),
    "shot without assist_event_id key": (15, _drop(["payload", "assist_event_id"])),
    "x outside pitch": (4, _set(["location", "x"], 120)),
    "bad event_id format": (4, _set(["event_id"], "ev_4")),
    "period 0 on in-play event": (4, _set(["period"], 0)),
    "tracking frame with player_id": (10, _set(["player_id"], "p_205")),
    "possession_change with player_id": (3, _set(["player_id"], "p_108")),
    "period_start bad direction": (2, _set(["payload", "home_attacking_towards"], "left")),
    "metadata not synthetic": (1, _set(["payload", "synthetic"], False)),
    "metadata with 21 players": (1, lambda e: e["payload"]["players"].pop()),
    "metadata with actor fields": (1, _set(["team_id"], "t_ngt")),
    "player speed impossible": (10, _set(["payload", "players", 0, "speed_kmh"], 80)),
    "bad emitted_at": (4, _set(["emitted_at"], "yesterday")),
    "schema_version major 2": (4, _set(["schema_version"], "2.0.0")),
    "unknown type": (4, _set(["type"], "dribble")),
}


@pytest.mark.parametrize("name", EVENT_MUTATIONS)
def test_event_schema_rejects(name):
    seq, mutate = EVENT_MUTATIONS[name]
    e = ev(seq)
    mutate(e)
    assert V.validate_event(e), f"expected rejection: {name}"


CLAIM_MUTATIONS = {
    "non-causal claim with no evidence": (1, _set(["evidence"], [])),
    "non-causal claim with depends_on": (1, _set(["depends_on"], ["cl_0000002"])),
    "causal claim with one dependency": (4, _set(["depends_on"], ["cl_0000002"])),
    "approx without tolerance": (1, _drop(["assertion", "tolerance"])),
    "unknown metric": (1, _set(["assertion", "metric"], "vibes")),
    "no english rendering": (1, lambda c: c.__setitem__("renderings", [c["renderings"][1]])),
    "unknown top-level field": (1, _set(["confidence_text"], "high")),
    "as_of_seq zero": (1, _set(["as_of_seq"], 0)),
    "entity_id wrong shape for type": (2, _set(["assertion", "subject", "entity_id"], "t_ald")),
    "salience above 1": (1, _set(["salience"], 1.2)),
    "evidence item with unknown kind": (1, _set(["evidence", 0, "kind"], "vibes")),
    "free-text causal (mechanism only)": (4, _drop(["assertion", "cause_claim_id"])),
}


@pytest.mark.parametrize("name", CLAIM_MUTATIONS)
def test_claim_schema_rejects(name):
    n, mutate = CLAIM_MUTATIONS[name]
    c = claim(n)
    mutate(c)
    assert V.validate_claim(c), f"expected rejection: {name}"


def test_verified_verdict_cannot_carry_failure_codes():
    v = copy.deepcopy(VERDICTS[0])
    v["failure_codes"] = ["wrong_value"]
    assert V.validate_verdict(v)


def test_verified_verdict_cannot_contain_a_failed_check():
    v = copy.deepcopy(VERDICTS[0])
    v["checks"][0]["status"] = "fail"
    assert V.validate_verdict(v)


def test_rejected_verdict_needs_a_code_and_a_failed_check():
    v = copy.deepcopy(VERDICTS[1])
    v["failure_codes"] = []
    assert V.validate_verdict(v)
    v = copy.deepcopy(VERDICTS[1])
    v["checks"][2]["status"] = "pass"
    assert V.validate_verdict(v)


# ------------------------------------------------------------- semantic rejections
def _stream_errors(mutate):
    events = copy.deepcopy(EVENTS)
    mutate(events)
    assert all(V.validate_event(e) == [] for e in events), "mutation must stay schema-valid"
    return V.check_event_stream(events)


def test_seq_gap_is_caught():
    def m(es):
        es[5]["seq"] = 9
    assert any("expected seq" in x for x in _stream_errors(m))


def test_event_id_must_follow_seq():
    def m(es):
        es[5]["event_id"] = "ev_0000099"
    assert any("does not match seq" in x for x in _stream_errors(m))


def test_clock_cannot_run_backwards():
    def m(es):
        es[6]["match_time_ms"] = 100
    assert any("goes backwards" in x for x in _stream_errors(m))


def test_unknown_player_is_caught():
    def m(es):
        es[3]["payload"]["receiver_id"] = "p_999"
    assert any("unknown player" in x for x in _stream_errors(m))


def test_player_on_wrong_team_is_caught():
    def m(es):
        es[3]["player_id"] = "p_205"
    assert any("does not belong" in x for x in _stream_errors(m))


def test_assist_must_point_backwards():
    def m(es):
        es[14]["payload"]["assist_event_id"] = "ev_0000016"
    assert any("earlier event" in x for x in _stream_errors(m))


def _claim_errors(mutate):
    claims = copy.deepcopy(CLAIMS)
    mutate(claims)
    assert all(V.validate_claim(c) == [] for c in claims), "mutation must stay schema-valid"
    return V.check_claims(claims, EVENTS)


def test_future_leak_via_event_evidence():
    def m(cs):
        cs[1]["evidence"].append({"kind": "event", "event_id": "ev_0000015"})
    assert any("future leak" in x for x in _claim_errors(m))


def test_future_leak_via_seq_range():
    def m(cs):
        cs[1]["evidence"] = [{"kind": "seq_range", "from_seq": 3, "to_seq": 12}]
    assert any("future leak" in x for x in _claim_errors(m))


def test_unknown_evidence_event():
    def m(cs):
        cs[0]["evidence"][0]["event_id"] = "ev_0000099"
    assert any("not in stream" in x for x in _claim_errors(m))


def test_window_must_be_closed_by_as_of_time():
    def m(cs):
        cs[0]["assertion"]["window"]["to_ms"] = 30000
    assert any("after the as_of event time" in x for x in _claim_errors(m))


def test_window_must_be_ordered():
    def m(cs):
        cs[1]["assertion"]["window"] = {"from_ms": 6000, "to_ms": 5000}
    assert any("from_ms must be < to_ms" in x for x in _claim_errors(m))


def test_causal_depends_on_must_match_cause_and_effect():
    def m(cs):
        cs[3]["depends_on"] = ["cl_0000002", "cl_0000001"]
    assert any("depends_on must equal" in x for x in _claim_errors(m))


def test_causal_order_violation():
    def m(cs):
        cs[1]["assertion"]["window"] = {"from_ms": 5000, "to_ms": 6100}
        cs[2]["assertion"]["window"] = {"from_ms": 4000, "to_ms": 5000}
    assert any("causal order violation" in x for x in _claim_errors(m))


def test_duplicate_rendering_language():
    def m(cs):
        cs[0]["renderings"].append(copy.deepcopy(cs[0]["renderings"][0]))
    assert any("duplicate rendering lang" in x for x in _claim_errors(m))


def test_verdict_for_unknown_claim():
    v = copy.deepcopy(VERDICTS)
    v[0]["claim_id"] = "cl_0000099"
    assert any("unknown claim" in x for x in V.check_verdicts(v, CLAIMS))


# ============================================================= overlays
def ov(n):
    return copy.deepcopy(OVERLAYS[n - 1])


def test_overlay_fixture_tells_the_whole_story():
    by = {o["overlay_id"]: o for o in OVERLAYS}
    assert by["ov_0000001"]["drop_reason"] == "unverified"   # rejected claim never reaches the screen
    assert by["ov_0000002"]["disposition"] == "scheduled"    # its rewrite does
    assert by["ov_0000003"]["drop_reason"] == "collision"    # lower-salience claim loses the slot
    assert {o["kind"] for o in OVERLAYS} == set(V.OVERLAY_KIND_TO_DEF)


def test_every_overlay_also_passes_the_root_oneof():
    root = Draft202012Validator({"$ref": V.URN + "overlay"}, registry=V.REGISTRY, format_checker=FormatChecker())
    for o in OVERLAYS:
        assert list(root.iter_errors(o)) == [], o["overlay_id"]


OVERLAY_MUTATIONS = {
    "unknown field": (2, _set(["extra"], 1)),
    "dropped without drop_reason": (1, _drop(["drop_reason"])),
    "scheduled with drop_reason": (2, _set(["drop_reason"], "stale")),
    "scheduled with displaced_by": (2, _set(["displaced_by"], "ov_0000001")),
    "preempted without displaced_by": (2, _set(["disposition"], "preempted")),
    "lower_third with two claims": (2, _set(["source", "claim_ids"], ["cl_0000005", "cl_0000003"])),
    "lower_third with no claims": (2, _set(["source", "claim_ids"], [])),
    "stat_card with no claims": (5, _set(["source", "claim_ids"], [])),
    "momentum_bar without snapshot": (6, _drop(["source", "snapshot_id"])),
    "momentum_bar citing a claim": (6, _set(["source", "claim_ids"], ["cl_0000001"])),
    "momentum_bar with three teams": (6, lambda o: o["payload"]["values"].append({"team_id": "t_ngt", "value": 1})),
    "momentum_bar value above 100": (6, _set(["payload", "values", 0, "value"], 140)),
    "player_tag citing a claim": (4, _set(["source", "claim_ids"], ["cl_0000001"])),
    "player_tag indicator zero threshold": (4, _set(["payload", "indicator", "threshold"], 0)),
    "priority above 100": (2, _set(["priority"], 101)),
    "duration too short": (2, _set(["timing", "duration_ms"], 100)),
    "bad lang": (2, _set(["lang"], "English")),
    "bad profile id": (2, _set(["profile_id"], "someone")),
    "unknown kind": (2, _set(["kind"], "scoreboard")),
    "missing stages_ms entry": (2, _drop(["latency", "stages_ms", "verify"])),
    "unknown unit": (5, _set(["payload", "metrics", 0, "unit"], "furlongs")),
}


@pytest.mark.parametrize("name", OVERLAY_MUTATIONS)
def test_overlay_schema_rejects(name):
    n, mutate = OVERLAY_MUTATIONS[name]
    o = ov(n)
    mutate(o)
    assert V.validate_overlay(o), f"expected rejection: {name}"


def _overlay_errors(mutate, require_reviewed=False, claims=None, verdicts=None):
    overlays = copy.deepcopy(OVERLAYS)
    mutate(overlays)
    assert all(V.validate_overlay(o) == [] for o in overlays), "mutation must stay schema-valid"
    return V.check_overlays(overlays, claims or CLAIMS, EVENTS, verdicts or VERDICTS, require_reviewed)


def test_rejected_claim_cannot_be_shown():
    def m(os_):
        os_[0]["disposition"] = "scheduled"
        del os_[0]["drop_reason"]
        os_[0]["timing"]["start_ms"] = 20000  # keep capacity out of the way
    errs = _overlay_errors(m)
    assert any("no verified verdict" in x for x in errs)
    assert any("superseded" in x for x in errs)


def test_claim_without_any_verdict_cannot_be_shown():
    verdicts = [v for v in VERDICTS if v["claim_id"] != "cl_0000001"]
    errs = _overlay_errors(lambda os_: None, verdicts=verdicts)
    assert any("cl_0000001 has no verified verdict" in x for x in errs)


def test_latest_verdict_wins():
    late = copy.deepcopy(VERDICTS[0])
    late.update(verdict_id="vd_0000099", attempt=2, status="rejected", failure_codes=["wrong_value"])
    late["checks"] = [{"check": "assertion_numeric_match", "status": "fail", "expected": 0.31, "observed": 0.4}]
    errs = _overlay_errors(lambda os_: None, verdicts=VERDICTS + [late])
    assert any("cl_0000001 has no verified verdict" in x for x in errs)


def test_unverified_drop_reason_must_be_true():
    def m(os_):
        os_[0]["source"]["claim_ids"] = ["cl_0000005"]
        os_[0]["payload"]["text"] = CLAIMS[4]["renderings"][0]["text"]
    assert any("every cited claim is verified" in x for x in _overlay_errors(m))


def test_overlay_cannot_start_before_its_trigger_event():
    def m(os_):
        os_[4]["timing"]["start_ms"] = 20000
    assert any("before its trigger event" in x for x in _overlay_errors(m))


def test_overlay_cannot_wait_too_long():
    def m(os_):
        os_[4]["timing"]["start_ms"] = 20500 + V.MAX_QUEUE_DELAY_MS["stat_card"] + 1
    assert any("over the stat_card limit" in x for x in _overlay_errors(m))


def test_trigger_cannot_precede_claim_basis():
    def m(os_):
        os_[4]["timing"]["trigger_seq"] = 14
        os_[4]["timing"]["start_ms"] = 18000
        os_[4]["latency"]["event_emitted_at"] = EVENTS[13]["emitted_at"]
    assert any("earlier than as_of_seq" in x for x in _overlay_errors(m))


def test_collision_drop_needs_a_full_slot():
    def m(os_):
        os_[2]["timing"]["start_ms"] = 14000  # ov_2 is gone by then, slot is free
    assert any("free capacity" in x for x in _overlay_errors(m))


def test_collision_drop_cannot_outrank_occupant():
    def m(os_):
        os_[2]["priority"] = 90
    assert any("outranks" in x for x in _overlay_errors(m))


def test_capacity_is_enforced():
    def m(os_):
        os_[2]["disposition"] = "scheduled"
        del os_[2]["drop_reason"]
    errs = _overlay_errors(m)
    assert any("capacity 1 exceeded" in x for x in errs)


def test_stale_drop_must_really_be_stale():
    def m(os_):
        os_[2]["drop_reason"] = "stale"
    assert any("within the limit" in x for x in _overlay_errors(m))


def _preempt_pair(os_, displacer_priority=80, displacer_start=9000):
    first = os_[1]
    first["disposition"] = "preempted"
    first["displaced_by"] = "ov_0000007"
    second = copy.deepcopy(first)
    second.update(overlay_id="ov_0000007", disposition="scheduled", priority=displacer_priority)
    second.pop("displaced_by")
    second["timing"] = {"trigger_seq": 9, "start_ms": displacer_start, "duration_ms": 4000}
    second["latency"]["event_emitted_at"] = EVENTS[8]["emitted_at"]
    second["latency"]["compiled_at"] = "2026-10-14T09:00:09.000Z"
    os_.append(second)


def test_valid_preemption_passes():
    overlays = copy.deepcopy(OVERLAYS)
    _preempt_pair(overlays)
    assert all(V.validate_overlay(o) == [] for o in overlays)
    assert V.check_overlays(overlays, CLAIMS, EVENTS, VERDICTS) == []


def test_preemption_by_lower_priority_is_caught():
    overlays = copy.deepcopy(OVERLAYS)
    _preempt_pair(overlays, displacer_priority=20)
    assert any("lower-priority" in x for x in V.check_overlays(overlays, CLAIMS, EVENTS, VERDICTS))


def test_preemption_must_happen_during_the_preempted_overlay():
    overlays = copy.deepcopy(OVERLAYS)
    _preempt_pair(overlays, displacer_start=14000)
    assert any("must start during" in x for x in V.check_overlays(overlays, CLAIMS, EVENTS, VERDICTS))


def test_lower_third_text_must_equal_the_claim_rendering():
    def m(os_):
        os_[1]["payload"]["text"] = "Aldermoor's pressing won the game."
    assert any("differs from the claim's en rendering" in x for x in _overlay_errors(m))


def test_stat_card_value_must_satisfy_the_claim():
    def m(os_):
        os_[4]["payload"]["metrics"][0]["value"] = 0.45
    assert any("violates the claim" in x for x in _overlay_errors(m))


def test_stat_card_unit_must_match_registry():
    def m(os_):
        os_[4]["payload"]["metrics"][0]["unit"] = "count"
    assert any("unit count is wrong for xg" in x for x in _overlay_errors(m))


def test_stat_card_claims_must_match_metrics():
    def m(os_):
        os_[4]["source"]["claim_ids"] = ["cl_0000001", "cl_0000002"]
    assert any("must equal the claims behind the metrics" in x for x in _overlay_errors(m))


def test_stat_card_needs_a_metric_value_claim():
    def m(os_):
        os_[4]["source"]["claim_ids"] = ["cl_0000002"]
        os_[4]["payload"]["metrics"][0]["claim_id"] = "cl_0000002"
    assert any("not a metric_value claim" in x for x in _overlay_errors(m))


def test_momentum_bar_cannot_use_future_data():
    def m(os_):
        os_[5]["payload"]["window"]["to_ms"] = 25000
    assert any("future data" in x for x in _overlay_errors(m))


def test_momentum_bar_must_cover_both_teams():
    def m(os_):
        os_[5]["payload"]["values"][1]["team_id"] = "t_ngt"
    assert any("two teams" in x for x in _overlay_errors(m))


def test_indicator_must_reach_its_threshold():
    def m(os_):
        os_[3]["payload"]["indicator"]["observed"] = 8.0
    assert any("below its threshold" in x for x in _overlay_errors(m))


def test_indicator_needs_a_snapshot():
    def m(os_):
        del os_[3]["source"]["snapshot_id"]
    assert any("needs a snapshot_id" in x for x in _overlay_errors(m))


def test_latency_must_match_the_trigger_event():
    def m(os_):
        os_[4]["latency"]["event_emitted_at"] = "2026-10-14T09:00:19.000Z"
    assert any("differs from the trigger event" in x for x in _overlay_errors(m))


def test_latency_stages_cannot_exceed_the_total():
    def m(os_):
        os_[4]["latency"]["stages_ms"]["verify"] = 900
    assert any("event-to-overlay was" in x for x in _overlay_errors(m))


def test_latency_cannot_run_backwards():
    def m(os_):
        os_[4]["latency"]["compiled_at"] = "2026-10-14T09:00:20.000Z"
    assert any("before event_emitted_at" in x for x in _overlay_errors(m))


def _swahili_overlay(reviewed):
    claims = copy.deepcopy(CLAIMS)
    claims[0]["renderings"][1]["human_reviewed"] = reviewed
    o = ov(2)
    o.update(overlay_id="ov_0000007", lang="sw")
    o["source"]["claim_ids"] = ["cl_0000001"]
    o["payload"] = {"kicker": "key_moment", "text": claims[0]["renderings"][1]["text"]}
    o["timing"] = {"trigger_seq": 15, "start_ms": 30000, "duration_ms": 5000}
    o["latency"]["event_emitted_at"] = EVENTS[14]["emitted_at"]
    o["latency"]["compiled_at"] = "2026-10-14T09:00:21.500Z"
    o["timing"]["start_ms"] = 21000
    overlays = [x for x in copy.deepcopy(OVERLAYS) if x["overlay_id"] not in ("ov_0000002",)] + [o]
    return overlays, claims


def test_unreviewed_swahili_passes_by_default_but_fails_the_demo_gate():
    overlays, claims = _swahili_overlay(reviewed=False)
    assert V.validate_overlay(overlays[-1]) == []
    assert not [e for e in V.check_overlays(overlays, claims, EVENTS, VERDICTS) if "reviewed" in e]
    gated = V.check_overlays(overlays, claims, EVENTS, VERDICTS, require_reviewed=True)
    assert any("not human reviewed" in x for x in gated)


def test_reviewed_swahili_passes_the_demo_gate():
    overlays, claims = _swahili_overlay(reviewed=True)
    gated = V.check_overlays(overlays, claims, EVENTS, VERDICTS, require_reviewed=True)
    assert not [e for e in gated if "reviewed" in e]


# ============================================================= eval labels
import hashlib
import shutil

EVAL_DIR = Path(__file__).parent / "examples" / "eval"
MANIFEST = json.loads((EVAL_DIR / "manifest.json").read_text(encoding="utf-8"))
LABELS = V.load_jsonl(EVAL_DIR / "labels.jsonl")
STREAMS = {"ngt-ald-demo01": EVENTS}


def lb(n):
    return copy.deepcopy(LABELS[n - 1])


def test_eval_set_fixture_passes_end_to_end():
    assert V.validate_eval_set(EVAL_DIR / "manifest.json") == []


def test_eval_set_covers_every_origin_and_split_and_both_outcomes():
    assert {l["origin"] for l in LABELS} == {"generated_clean", "generated_corrupted", "hand_written"}
    assert {l["split"] for l in LABELS} == {"dev", "test"}
    assert {l["expected"]["status"] for l in LABELS} == {"verified", "rejected"}
    test_codes = {c for l in LABELS if l["split"] == "test" for c in l["expected"]["failure_codes"]}
    assert test_codes, "the held-out split must contain at least one failure to measure"


def test_every_operator_maps_to_a_distinct_code_with_a_reporting_check():
    codes = list(V.CORRUPTION_OPERATORS.values())
    assert len(codes) == len(set(codes))
    assert set(codes) == set(V.FAILURE_CODE_CHECKS)
    assert all(V.FAILURE_CODE_CHECKS[c] for c in codes)


def test_the_corrupted_fixtures_really_are_schema_valid_claims():
    for l in LABELS:
        assert V.validate_claim(l["claim"]) == [], l["label_id"]


EVAL_MUTATIONS = {
    "unknown field": (1, _set(["extra"], 1)),
    "bad label id": (1, _set(["label_id"], "lb_1")),
    "bad split": (1, _set(["split"], "train")),
    "bad difficulty": (1, _set(["difficulty"], "hard")),
    "clean label expecting rejection": (1, _set(["expected", "status"], "rejected")),
    "clean label with a corruption block": (1, _set(["corruption"], {"operator": "perturb_value", "base_label_id": "lb_0000002", "detail": "x"})),
    "corrupted label without corruption block": (5, _drop(["corruption"])),
    "corrupted label expecting verified": (5, _set(["expected", "status"], "verified")),
    "unknown operator": (5, _set(["corruption", "operator"], "make_it_wrong")),
    "verified with failure codes": (1, _set(["expected", "failure_codes"], ["wrong_value"])),
    "verified with failed checks": (1, _set(["expected", "failed_checks"], ["evidence_resolves"])),
    "verified with rewritable": (1, _set(["expected", "rewritable"], True)),
    "rejected without failure codes": (5, _set(["expected", "failure_codes"], [])),
    "rejected without failed checks": (5, _set(["expected", "failed_checks"], [])),
    "rejected without rewritable": (5, _drop(["expected", "rewritable"])),
    "schema_invalid is not a valid label code": (5, _set(["expected", "failure_codes"], ["schema_invalid"])),
    "embedded claim is invalid": (5, _set(["claim", "evidence"], [])),
    "duplicate expected codes": (5, _set(["expected", "failure_codes"], ["wrong_value", "wrong_value"])),
}


@pytest.mark.parametrize("name", EVAL_MUTATIONS)
def test_eval_label_schema_rejects(name):
    n, mutate = EVAL_MUTATIONS[name]
    l = lb(n)
    mutate(l)
    assert V.validate_eval_label(l), f"expected rejection: {name}"


def _eval_errors(mutate):
    labels = copy.deepcopy(LABELS)
    manifest = copy.deepcopy(MANIFEST)
    mutate(labels, manifest)
    assert all(V.validate_eval_label(l) == [] for l in labels), "mutation must stay schema-valid"
    return V.check_eval_set(manifest, labels, STREAMS)


def test_label_count_must_match_manifest():
    assert any("label_count" in x for x in _eval_errors(lambda ls, m: m.update(label_count=3)))


def test_stream_event_count_must_match_manifest():
    assert any("events, manifest says" in x for x in _eval_errors(lambda ls, m: m["streams"][0].update(event_count=99)))


def test_duplicate_label_id():
    def m(ls, man):
        ls[1]["label_id"] = ls[0]["label_id"]
    assert any("duplicate label_id" in x for x in _eval_errors(m))


def test_duplicate_claim_id_across_labels():
    def m(ls, man):
        ls[1]["claim"]["claim_id"] = ls[0]["claim"]["claim_id"]
    assert any("duplicate claim_id" in x for x in _eval_errors(m))


def test_label_for_a_match_the_manifest_does_not_list():
    def m(ls, man):
        for l in ls:
            l["claim"]["match_id"] = "other-match-01"
    assert any("does not list" in x for x in _eval_errors(m))


def test_corrupted_label_cannot_leak_across_splits():
    def m(ls, man):
        ls[4]["split"] = "test"   # base lb_0000001 is dev
    assert any("leakage" in x for x in _eval_errors(m))


def test_corruption_must_change_something():
    def m(ls, man):
        ls[4]["claim"] = {**copy.deepcopy(ls[0]["claim"]), "claim_id": "cl_0000101"}
    assert any("identical to its base" in x for x in _eval_errors(m))


def test_base_label_must_exist_and_be_clean():
    def missing(ls, man):
        ls[4]["corruption"]["base_label_id"] = "lb_0000099"
    assert any("not found" in x for x in _eval_errors(missing))

    def not_clean(ls, man):
        ls[4]["corruption"]["base_label_id"] = "lb_0000014"
    assert any("must be generated_clean" in x for x in _eval_errors(not_clean))


def test_operator_must_provoke_an_expected_code():
    def m(ls, man):
        ls[4]["corruption"]["operator"] = "swap_player"
    assert any("should provoke wrong_player" in x for x in _eval_errors(m))


def test_failed_checks_must_be_explained_by_codes():
    def m(ls, man):
        ls[4]["expected"]["failed_checks"] = ["translation_fidelity"]
    errs = _eval_errors(m)
    assert any("not reported by any of the expected codes" in x for x in errs)
    assert any("needs one of" in x for x in errs)


def test_clean_label_that_the_deterministic_layer_rejects_is_caught():
    def m(ls, man):
        ls[0]["claim"]["evidence"][0]["event_id"] = "ev_0000099"
    assert any("labelled verified but" in x for x in _eval_errors(m))


def test_future_leak_label_must_really_leak():
    def m(ls, man):
        ls[7]["claim"]["evidence"] = ls[7]["claim"]["evidence"][:1]
    assert any("expects future_leak" in x for x in _eval_errors(m))


def test_causal_order_label_must_really_be_out_of_order():
    def m(ls, man):
        ls[9]["claim"]["assertion"]["cause_claim_id"], ls[9]["claim"]["assertion"]["effect_claim_id"] = (
            ls[9]["claim"]["assertion"]["effect_claim_id"], ls[9]["claim"]["assertion"]["cause_claim_id"])
        ls[9]["claim"]["depends_on"] = ls[9]["claim"]["depends_on"][::-1]
    assert any("expects causal_order_violation" in x for x in _eval_errors(m))


def test_translation_drift_needs_a_translation():
    def m(ls, man):
        ls[11]["claim"]["renderings"] = ls[11]["claim"]["renderings"][:1]
    assert any("needs a translated rendering" in x for x in _eval_errors(m))


# ---- the manifest pins exact bytes
def _copy_evalset(tmp_path):
    shutil.copytree(EVAL_DIR, tmp_path / "eval")
    shutil.copytree(EVAL_DIR.parent / "valid", tmp_path / "valid")
    return tmp_path / "eval" / "manifest.json"


def test_tampered_labels_are_detected(tmp_path):
    mp = _copy_evalset(tmp_path)
    lp = mp.parent / "labels.jsonl"
    lp.write_text(lp.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert any("labels_sha256" in x for x in V.validate_eval_set(mp))


def test_tampered_stream_is_detected(tmp_path):
    mp = _copy_evalset(tmp_path)
    sp = tmp_path / "valid" / "match_stream.jsonl"
    sp.write_text(sp.read_text(encoding="utf-8").replace("Northgate FC", "Northgate FX"), encoding="utf-8")
    assert any("sha256 for" in x for x in V.validate_eval_set(mp))


def test_missing_files_are_reported(tmp_path):
    mp = _copy_evalset(tmp_path)
    (mp.parent / "labels.jsonl").unlink()
    assert any("labels_file" in x and "not found" in x for x in V.validate_eval_set(mp))


MANIFEST_MUTATIONS = {
    "unknown field": _set(["extra"], 1),
    "bad set_id": _set(["set_id"], "demo"),
    "bad sha256": _set(["labels_sha256"], "abc"),
    "no streams": _set(["streams"], []),
    "absolute-looking path with spaces": _set(["labels_file"], "my labels.jsonl"),
    "bad set_version": _set(["set_version"], "v1"),
    "zero labels": _set(["label_count"], 0),
}


@pytest.mark.parametrize("name", MANIFEST_MUTATIONS)
def test_manifest_schema_rejects(name):
    m = copy.deepcopy(MANIFEST)
    MANIFEST_MUTATIONS[name](m)
    assert V.validate_eval_manifest(m), f"expected rejection: {name}"


# ============================================================= reference stats engine
import stats_ref as S

W_ALL = {"from_ms": 0, "to_ms": 20500}
NGT = {"entity_type": "team", "entity_id": "t_ngt"}
ALD = {"entity_type": "team", "entity_id": "t_ald"}
P205 = {"entity_type": "player", "entity_id": "p_205"}
MATCH_SUBJ = {"entity_type": "match", "entity_id": "ngt-ald-demo01"}
CTX = S.StatsContext(EVENTS, 15)


def approx(a, b, tol=6e-5):
    return a is not None and abs(a - b) <= tol


# every expected value below was worked out by hand from examples/valid/match_stream.jsonl
HAND = [
    (NGT, "goals", 1), (NGT, "shots", 1), (NGT, "shots_on_target", 1), (NGT, "xg", 0.31), (ALD, "xg", 0.0),
    (NGT, "passes", 3), (ALD, "passes", 2),
    (NGT, "pass_accuracy_pct", 100.0), (ALD, "pass_accuracy_pct", 50.0),
    (ALD, "tackles_won", 1), (ALD, "pressures", 1), (NGT, "pressures", 0),
    # possession: ngt 6100 + 8400 of 20500 ms; ald 6000 of 20500 ms
    (NGT, "possession_pct", 100 * 14500 / 20500), (ALD, "possession_pct", 100 * 6000 / 20500),
    # control = 100 * (0.6 * share + 0.4 * stability); stable spells are >= 8000 ms: ngt 1 of 2, ald 0 of 1
    (NGT, "control_index", 100 * (0.6 * 14500 / 20500 + 0.4 * 0.5)), (ALD, "control_index", 100 * (0.6 * 6000 / 20500)),
    # pressure: (tackles + pressures + fouls) per minute / 6 per minute; ald has 2 in 20.5 s
    (ALD, "pressure_index", 100 * (2 / (20500 / 60000)) / 6), (NGT, "pressure_index", 0.0),
    # rhythm: (passes + shots + tackles + fouls) per minute / 30 per minute
    (NGT, "rhythm_index", 100 * (4 / (20500 / 60000)) / 30), (ALD, "rhythm_index", 100 * (3 / (20500 / 60000)) / 30),
    # ppda for ald: ngt passes from x >= 42 m (3) over ald actions with x >= 42 m (pressure + tackle = 2)
    (ALD, "ppda", 1.5),
    (NGT, "avg_pass_length_m", (math.hypot(7.5, 4) + math.hypot(12, 10) + math.hypot(28, 7)) / 3),
    (P205, "top_speed_kmh", 12.4), (NGT, "top_speed_kmh", 6.1), (ALD, "top_speed_kmh", 12.4),
    (P205, "distance_km", 0.0002), (NGT, "sprints", 0),
    (MATCH_SUBJ, "max_ball_speed_kmh", 96.4), (NGT, "max_shot_speed_kmh", 96.4),
]


@pytest.mark.parametrize("subject,metric,expected", HAND, ids=[f"{s['entity_id']}-{m}" for s, m, _ in HAND])
def test_reference_engine_matches_hand_calculation(subject, metric, expected):
    assert approx(CTX.metric(subject, metric, W_ALL), expected)


def test_ppda_is_undefined_without_defensive_actions():
    assert CTX.metric(NGT, "ppda", W_ALL) is None


def test_undefined_metrics_are_none_not_zero():
    early = {"from_ms": 0, "to_ms": 1000}
    assert CTX.metric(NGT, "pass_accuracy_pct", early) is None
    assert CTX.metric(NGT, "avg_pass_length_m", early) is None
    assert CTX.metric(NGT, "distance_km", early) is None
    assert CTX.metric(MATCH_SUBJ, "max_ball_speed_kmh", early) is None


def test_pass_difficulty_worked_example():
    # seq 9: 12.083 m, ground, 11 m forward for the away side (attacks -x), nearest defender 1.2806 m away
    expected = 0.4 * (math.hypot(11, 5) / 40) + 0.0 + 0.2 * (11 / 30) + 0.2 * (1 - math.hypot(1, 0.8) / 10)
    assert approx(CTX.pass_difficulty(EVENTS[8]), expected, 1e-9)


def test_pass_difficulty_stays_between_zero_and_one():
    for e in EVENTS:
        if e["type"] == "pass":
            assert 0.0 <= CTX.pass_difficulty(e) <= 1.0


def test_engine_only_sees_events_up_to_as_of_seq():
    early = S.StatsContext(EVENTS, 14)
    assert early.metric(NGT, "shots", {"from_ms": 0, "to_ms": 20500}) == 0
    assert early.metric(NGT, "xg", {"from_ms": 0, "to_ms": 20500}) == 0


def test_possession_span_ends_at_period_end():
    full = S.StatsContext(EVENTS, 16)
    w = {"from_ms": 0, "to_ms": 2820000}
    assert approx(full.metric(NGT, "possession_pct", w) + full.metric(ALD, "possession_pct", w), 100.0, 1e-3)


def test_sprint_needs_a_full_second_of_consecutive_fast_frames():
    ev = copy.deepcopy(EVENTS[:15])
    base = ev[9]
    frames = []
    for i in range(6):          # 6 frames at 5 Hz = 1000 ms between first and last
        f = copy.deepcopy(base)
        f["payload"]["frame_index"] = 100 + i
        f["payload"]["players"] = [{"player_id": "p_205", "x": 60.0, "y": 30.0, "speed_kmh": 27.0}]
        f["match_time_ms"] = 9000 + 200 * i
        frames.append(f)
    ev = ev[:10] + frames + ev[10:]
    for i, e in enumerate(ev, start=1):
        e["seq"], e["event_id"] = i, f"ev_{i:07d}"
    w = {"from_ms": 8500, "to_ms": 10500}
    assert S.StatsContext(ev, len(ev)).metric(P205, "sprints", w) == 1
    short = {"from_ms": 8500, "to_ms": 9800}      # only 4 frames: 600 ms, not a sprint
    assert S.StatsContext(ev, len(ev)).metric(P205, "sprints", short) == 0


# ============================================================= snapshots
SNAPS = json.loads((EX / "snapshots.json").read_text(encoding="utf-8"))
PROFILES = json.loads((EX / "profiles.json").read_text(encoding="utf-8"))
STATE = json.loads((EX / "match_state.json").read_text(encoding="utf-8"))
RECAP = json.loads((EX / "recap.json").read_text(encoding="utf-8"))


def snap(n):
    return copy.deepcopy(SNAPS[n - 1])


def test_shared_state_fixtures_pass_everything():
    assert V.validate_all(EVENTS, CLAIMS, VERDICTS, OVERLAYS, require_reviewed=True,
                          snapshots=SNAPS, profiles=PROFILES, state=STATE, recap=RECAP) == []


SNAP_MUTATIONS = {
    "unknown field": (1, _set(["extra"], 1)),
    "unknown metric": (1, _set(["entities", 0, "metrics", "vibes"], 1)),
    "empty metrics": (1, _set(["entities", 0, "metrics"], {})),
    "non-numeric value": (1, _set(["entities", 0, "metrics", "xg"], "high")),
    "no entities": (1, _set(["entities"], [])),
    "bad snapshot id": (1, _set(["snapshot_id"], "snap_1")),
    "bad engine version": (1, _set(["stats_engine_version"], "latest")),
    "unknown entity type": (1, _set(["entities", 0, "subject", "entity_type"], "club")),
}


@pytest.mark.parametrize("name", SNAP_MUTATIONS)
def test_snapshot_schema_rejects(name):
    n, mutate = SNAP_MUTATIONS[name]
    s = snap(n)
    mutate(s)
    assert V.validate_snapshot(s), f"expected rejection: {name}"


def _snap_errors(mutate):
    snaps = copy.deepcopy(SNAPS)
    mutate(snaps)
    assert all(V.validate_snapshot(x) == [] for x in snaps), "mutation must stay schema-valid"
    return V.check_snapshots(snaps, EVENTS)


def test_wrong_snapshot_value_is_caught_by_recomputation():
    errs = _snap_errors(lambda ss: ss[0]["entities"][0]["metrics"].__setitem__("xg", 0.45))
    assert any("reference engine computes 0.31" in x for x in errs)


def test_rounding_noise_is_tolerated_but_real_drift_is_not():
    assert _snap_errors(lambda ss: ss[0]["entities"][0]["metrics"].__setitem__("xg", 0.31004)) == []
    assert _snap_errors(lambda ss: ss[0]["entities"][0]["metrics"].__setitem__("xg", 0.3102))


def test_snapshot_cannot_list_an_undefined_metric():
    errs = _snap_errors(lambda ss: ss[1]["entities"][0]["metrics"].__setitem__("distance_km", 0.5))
    assert any("undefined in this window" in x for x in errs)


def test_snapshot_metric_must_fit_the_subject_type():
    errs = _snap_errors(lambda ss: ss[0]["entities"][0]["metrics"].__setitem__("max_ball_speed_kmh", 96.4))
    assert any("not defined for a team" in x for x in errs)


def test_snapshot_window_cannot_reach_past_its_event():
    errs = _snap_errors(lambda ss: ss[0]["window"].__setitem__("to_ms", 25000))
    assert any("future data" in x for x in errs)


def test_snapshot_unknown_subject_and_duplicates():
    def unknown(ss):
        ss[1]["entities"][0]["subject"]["entity_id"] = "p_999"
    assert any("unknown player" in x for x in _snap_errors(unknown))

    def dup(ss):
        ss[0]["entities"].append(copy.deepcopy(ss[0]["entities"][0]))
    assert any("duplicate subject" in x for x in _snap_errors(dup))


def test_snapshot_from_another_engine_version_is_flagged():
    errs = _snap_errors(lambda ss: ss[0].__setitem__("stats_engine_version", "0.2.0"))
    assert any("this validator implements" in x for x in errs)


def test_duplicate_snapshot_id():
    assert any("duplicate snapshot_id" in x for x in _snap_errors(lambda ss: ss[1].__setitem__("snapshot_id", ss[0]["snapshot_id"])))


# ---- claims that cite snapshots
def _claim_snap_errors(mutate):
    claims, snaps = copy.deepcopy(CLAIMS), copy.deepcopy(SNAPS)
    mutate(claims, snaps)
    assert all(V.validate_claim(c) == [] for c in claims)
    return V.check_claims(claims, EVENTS, snaps)


def test_claim_citing_a_matching_snapshot_passes():
    assert _claim_snap_errors(lambda c, s: None) == []


def test_claim_citing_an_unknown_snapshot():
    def m(c, s):
        c[0]["evidence"][2]["snapshot_id"] = "snap_0000099"
    assert any("unknown snapshot" in x for x in _claim_snap_errors(m))


def test_claim_contradicting_its_snapshot():
    def m(c, s):
        s[0]["entities"][0]["metrics"]["xg"] = 0.5
    assert any("contradicts the assertion" in x for x in _claim_snap_errors(m))


def test_claim_snapshot_window_must_match():
    def m(c, s):
        s[0]["window"]["from_ms"] = 1000
    assert any("window differs" in x for x in _claim_snap_errors(m))


def test_claim_snapshot_must_not_be_newer_than_the_claim():
    def m(c, s):
        c[0]["as_of_seq"] = 14
        c[0]["evidence"] = [{"kind": "event", "event_id": "ev_0000014"}, c[0]["evidence"][2]]
        c[0]["assertion"]["window"] = {"from_ms": 0, "to_ms": 18000}
    errs = _claim_snap_errors(m)
    assert any("newer than as_of_seq" in x for x in errs)


def test_claim_snapshot_as_of_must_agree():
    def m(c, s):
        c[0]["evidence"][2]["as_of_seq"] = 14
    assert any("differs from the snapshot's" in x for x in _claim_snap_errors(m))


def test_claim_snapshot_must_contain_the_subject_and_metric():
    def m(c, s):
        del s[0]["entities"][0]["metrics"]["xg"]
    assert any("has no xg" in x for x in _claim_snap_errors(m))


# ---- overlays that cite snapshots and profiles
def _ov_state_errors(mutate, **kw):
    overlays, snaps, profs = copy.deepcopy(OVERLAYS), copy.deepcopy(SNAPS), copy.deepcopy(PROFILES)
    mutate(overlays, snaps, profs)
    assert all(V.validate_overlay(o) == [] for o in overlays)
    return V.check_overlays(overlays, CLAIMS, EVENTS, VERDICTS, snapshots=snaps, profiles=profs, **kw)


def test_overlays_with_snapshots_and_profiles_pass():
    assert _ov_state_errors(lambda o, s, p: None) == []


def test_momentum_values_must_equal_the_snapshot():
    def m(o, s, p):
        o[5]["payload"]["values"][0]["value"] = 64.0
    assert any("snapshot snap_0000003 has" in x for x in _ov_state_errors(m))


def test_momentum_window_must_equal_the_snapshot_window():
    def m(o, s, p):
        o[5]["payload"]["window"]["from_ms"] = 500
    assert any("window differs from snapshot" in x for x in _ov_state_errors(m))


def test_overlay_cannot_cite_a_newer_snapshot_than_its_trigger():
    def m(o, s, p):
        o[3]["source"]["snapshot_id"] = "snap_0000001"   # as_of 15, trigger_seq 10
    assert any("newer than trigger_seq" in x for x in _ov_state_errors(m))


def test_overlay_cites_an_unknown_snapshot():
    def m(o, s, p):
        o[5]["source"]["snapshot_id"] = "snap_0000099"
    assert any("unknown snapshot" in x for x in _ov_state_errors(m))


def test_speed_indicator_must_equal_the_trigger_frame():
    def m(o, s, p):
        o[3]["payload"]["indicator"]["observed"] = 14.0
    assert any("differs from the trigger frame" in x for x in _ov_state_errors(m))


def test_overlay_for_an_unknown_profile():
    def m(o, s, p):
        o[1]["profile_id"] = "prof_nobody"
    assert any("unknown profile" in x for x in _ov_state_errors(m))


def test_overlay_language_must_match_its_profile():
    def m(o, s, p):
        o[1]["profile_id"] = "prof_casual_sw"
    assert any("differs from profile" in x for x in _ov_state_errors(m))


def test_density_floor_filters_low_priority_overlays():
    def m(o, s, p):
        p[0]["density"] = "standard"      # floor 40: momentum bar (35) falls below it
    errs = _ov_state_errors(m)
    assert any("below the standard density floor" in x for x in errs)


def test_dropped_overlays_are_not_held_to_the_density_floor():
    def m(o, s, p):
        p[0]["density"] = "minimal"       # floor 70; only ov_0000001 and ov_0000003 are dropped
    errs = _ov_state_errors(m)
    assert not any("ov_0000001" in x or "ov_0000003" in x for x in errs if "density floor" in x)


# ============================================================= profiles
def prof(n):
    return copy.deepcopy(PROFILES[n - 1])


PROFILE_MUTATIONS = {
    "unknown field": (1, _set(["email"], "a@b.c")),
    "bad mode": (1, _set(["mode"], "pundit")),
    "bad density": (1, _set(["density"], "dense")),
    "three favorite teams": (1, _set(["favorite_team_ids"], ["t_ngt", "t_ald", "t_xyz"])),
    "four favorite players": (1, _set(["favorite_player_ids"], ["p_101", "p_102", "p_103", "p_104"])),
    "duplicate favorites": (2, _set(["favorite_player_ids"], ["p_110", "p_110"])),
    "player focus without player": (2, _drop(["focus", "player_id"])),
    "metric focus with unknown metric": (1, _set(["focus", "metric"], "vibes")),
    "focus of unknown kind": (1, _set(["focus", "kind"], "team")),
    "bad lang": (1, _set(["lang"], "English")),
}


@pytest.mark.parametrize("name", PROFILE_MUTATIONS)
def test_profile_schema_rejects(name):
    n, mutate = PROFILE_MUTATIONS[name]
    p = prof(n)
    mutate(p)
    assert V.validate_profile(p), f"expected rejection: {name}"


def test_profile_references_must_exist_in_the_match():
    def run(mutate):
        ps = copy.deepcopy(PROFILES)
        mutate(ps)
        return V.check_profiles(ps, EVENTS)

    assert run(lambda ps: None) == []
    assert any("favorite team" in x for x in run(lambda ps: ps[0].__setitem__("favorite_team_ids", ["t_nope"])))
    assert any("favorite player" in x for x in run(lambda ps: ps[1].__setitem__("favorite_player_ids", ["p_999"])))
    assert any("focus player" in x for x in run(lambda ps: ps[1]["focus"].__setitem__("player_id", "p_999")))
    assert any("duplicate profile_id" in x for x in run(lambda ps: ps[1].__setitem__("profile_id", "prof_analyst_en")))


# ============================================================= match state
STATE_MUTATIONS = {
    "unknown field": _set(["extra"], 1),
    "bad status": _set(["status"], "paused"),
    "one team in score": _set(["score"], [{"team_id": "t_ngt", "goals": 1}]),
    "negative goals": _set(["score", 0, "goals"], -1),
    "13 key moments": _set(["key_moments"], [{"claim_id": "cl_0000001", "rank": 1}] * 13),
    "missing snapshot": _drop(["snapshot_id"]),
}


@pytest.mark.parametrize("name", STATE_MUTATIONS)
def test_match_state_schema_rejects(name):
    s = copy.deepcopy(STATE)
    STATE_MUTATIONS[name](s)
    assert V.validate_match_state(s), f"expected rejection: {name}"


def _state_errors(mutate, claims=None, verdicts=None):
    s = copy.deepcopy(STATE)
    mutate(s)
    assert V.validate_match_state(s) == []
    return V.check_match_state(s, EVENTS, claims or CLAIMS, verdicts or VERDICTS, SNAPS)


def test_match_state_fixture_passes():
    assert _state_errors(lambda s: None) == []


def test_state_score_is_recomputed_from_the_stream():
    assert any("score for t_ngt" in x for x in _state_errors(lambda s: s["score"][0].__setitem__("goals", 2)))


def test_state_status_is_derived_from_the_stream():
    assert any("status is full_time" in x for x in _state_errors(lambda s: s.__setitem__("status", "full_time")))
    assert any("status is live" in x for x in _state_errors(lambda s: s.__setitem__("status", "live")))


def test_state_key_moments_must_be_the_top_of_the_eligible_claims():
    def reorder(s):
        s["key_moments"][0], s["key_moments"][1] = s["key_moments"][1], s["key_moments"][0]
        s["key_moments"][0]["rank"], s["key_moments"][1]["rank"] = 1, 2
    assert any("not the top of the eligible claims" in x for x in _state_errors(reorder))

    def drop(s):
        s["key_moments"].pop()
    assert any("not the top of the eligible claims" in x for x in _state_errors(drop))


def test_state_cannot_feature_a_rejected_or_superseded_claim():
    def m(s):
        s["key_moments"].append({"claim_id": "cl_0000004", "rank": 5})
    assert any("not the top" in x for x in _state_errors(m))


def test_state_ranks_must_run_in_order():
    def m(s):
        s["key_moments"][1]["rank"] = 5
    assert any("ranks must run" in x for x in _state_errors(m))


def test_state_snapshot_must_cover_the_whole_match_so_far():
    assert any("snapshot as_of_seq differs" in x for x in _state_errors(lambda s: s.__setitem__("snapshot_id", "snap_0000001")))
    assert any("snapshot snap_0000099 not found" in x for x in _state_errors(lambda s: s.__setitem__("snapshot_id", "snap_0000099")))


def test_claims_from_the_future_are_not_eligible_for_a_state():
    ids = [c["claim_id"] for c in V.eligible_claims(CLAIMS, VERDICTS, 14)]
    assert "cl_0000001" not in ids      # its as_of_seq is 15
    assert "cl_0000002" in ids          # as_of_seq 8
    assert "cl_0000004" not in ids      # rejected and superseded


def test_eligible_claims_are_ordered_by_salience_then_id():
    got = [c["claim_id"] for c in V.eligible_claims(CLAIMS, VERDICTS, 16)]
    assert got == ["cl_0000001", "cl_0000005", "cl_0000002", "cl_0000003"]
    tied = copy.deepcopy(CLAIMS)
    tied[2]["salience"] = tied[1]["salience"]
    tied_ids = [c["claim_id"] for c in V.eligible_claims(tied, VERDICTS, 16)]
    assert tied_ids.index("cl_0000002") < tied_ids.index("cl_0000003")


# ============================================================= recap
RECAP_MUTATIONS = {
    "unknown field": _set(["headline"], "x"),
    "bad kind": _set(["kind"], "live"),
    "no sections": _set(["sections"], []),
    "seven sections": _set(["sections"], [copy.deepcopy(RECAP["sections"][0])] * 7),
    "bad heading": _set(["sections", 0, "heading"], "gossip"),
    "five claims in one section": _set(["sections", 0, "claim_ids"], ["cl_0000001", "cl_0000002", "cl_0000003", "cl_0000004", "cl_0000005"]),
    "empty text": _set(["sections", 0, "text"], ""),
    "bad recap id": _set(["recap_id"], "recap1"),
}


@pytest.mark.parametrize("name", RECAP_MUTATIONS)
def test_recap_schema_rejects(name):
    r = copy.deepcopy(RECAP)
    RECAP_MUTATIONS[name](r)
    assert V.validate_recap(r), f"expected rejection: {name}"


def _recap_errors(mutate, **kw):
    r = copy.deepcopy(RECAP)
    mutate(r)
    assert V.validate_recap(r) == []
    return V.check_recap(r, kw.pop("claims", CLAIMS), kw.pop("verdicts", VERDICTS), EVENTS, STATE, PROFILES, **kw)


def test_recap_fixture_passes():
    assert _recap_errors(lambda r: None) == []


def test_recap_text_must_be_the_claims_renderings():
    errs = _recap_errors(lambda r: r["sections"][0].__setitem__("text", "Northgate dominated the half."))
    assert any("joined by spaces" in x for x in errs)


def test_recap_cannot_cite_a_rejected_or_superseded_claim():
    def m(r):
        r["sections"][1]["claim_ids"] = ["cl_0000002", "cl_0000004"]
        r["sections"][1]["text"] = " ".join([CLAIMS[1]["renderings"][0]["text"], CLAIMS[3]["renderings"][0]["text"]])
    errs = _recap_errors(m)
    assert any("cl_0000004 is not verified, is superseded" in x for x in errs)
    assert any("not one of the match state's key moments" in x for x in errs)


def test_recap_cannot_use_the_same_claim_twice():
    def m(r):
        r["sections"][1]["claim_ids"] = ["cl_0000001", "cl_0000005"]
        r["sections"][1]["text"] = " ".join([CLAIMS[0]["renderings"][0]["text"], CLAIMS[4]["renderings"][0]["text"]])
    assert any("used twice" in x for x in _recap_errors(m))


def test_recap_claims_must_be_key_moments():
    state = copy.deepcopy(STATE)
    state["key_moments"] = [x for x in state["key_moments"] if x["claim_id"] != "cl_0000003"]
    r = copy.deepcopy(RECAP)
    r["sections"][0]["claim_ids"] = ["cl_0000003"]
    r["sections"][0]["text"] = CLAIMS[2]["renderings"][0]["text"]
    assert any("not one of the match state's key moments" in x
               for x in V.check_recap(r, CLAIMS, VERDICTS, EVENTS, state, PROFILES))
    # the same section is fine when cl_0000003 really is a key moment
    assert not any("key moments" in x for x in V.check_recap(r, CLAIMS, VERDICTS, EVENTS, STATE, PROFILES))


def test_recap_must_match_the_state_it_was_built_from():
    assert any("kind full_time but the match is half_time" in x for x in _recap_errors(lambda r: r.__setitem__("kind", "full_time")))
    assert any("as_of_seq differs" in x for x in _recap_errors(lambda r: r.__setitem__("as_of_seq", 15)))


def test_recap_language_must_match_its_profile():
    def m(r):
        r["profile_id"] = "prof_casual_sw"
    assert any("differs from profile" in x for x in _recap_errors(m))


def test_recap_needs_a_rendering_in_its_language():
    def m(r):
        r["lang"] = "sw"
        r["profile_id"] = "prof_casual_sw"
    errs = _recap_errors(m)
    assert any("has no sw rendering" in x for x in errs)


def test_unreviewed_swahili_recap_fails_the_demo_gate():
    claims = copy.deepcopy(CLAIMS)
    claims[0]["renderings"][1]["human_reviewed"] = False
    r = copy.deepcopy(RECAP)
    r.update(lang="sw", profile_id="prof_casual_sw")
    r["sections"] = [{"heading": "numbers", "claim_ids": ["cl_0000001"], "text": claims[0]["renderings"][1]["text"]}]
    state = copy.deepcopy(STATE)
    state["key_moments"] = STATE["key_moments"]
    free = V.check_recap(r, claims, VERDICTS, EVENTS, state, PROFILES)
    gated = V.check_recap(r, claims, VERDICTS, EVENTS, state, PROFILES, require_reviewed=True)
    assert not any("reviewed" in x for x in free)
    assert any("not human reviewed" in x for x in gated)
    claims[0]["renderings"][1]["human_reviewed"] = True
    assert not any("reviewed" in x for x in V.check_recap(r, claims, VERDICTS, EVENTS, state, PROFILES, require_reviewed=True))


# ============================================================= every contract is exercised
def test_every_schema_file_has_a_fixture_and_a_validator():
    names = {p.name for p in V.SCHEMA_DIR.glob("*.schema.json")}
    assert names == {"common.schema.json", "claim.schema.json", "event.schema.json", "overlay.schema.json",
                     "verdict.schema.json", "eval-label.schema.json", "eval-manifest.schema.json",
                     "snapshot.schema.json", "profile.schema.json", "match-state.schema.json", "recap.schema.json"}


def test_metric_scope_covers_the_whole_registry():
    registry = json.loads((V.SCHEMA_DIR / "common.schema.json").read_text(encoding="utf-8"))
    ids = set(registry["$defs"]["MetricId"]["enum"])
    assert set(V.METRIC_SCOPE) == ids == set(V.METRIC_UNITS)
    for m in ids:
        assert hasattr(S.StatsContext, "_m_" + m), f"reference engine is missing {m}"
