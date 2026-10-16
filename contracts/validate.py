"""Receipts contract validation: JSON Schema (draft 2020-12) plus semantic checks.

Usage:
    python validate.py events.jsonl [--claims F] [--verdicts F] [--overlays F] [--snapshots F]
                       [--profiles F] [--state F] [--recap F] [--require-reviewed]
    python validate.py --eval examples/eval/manifest.json

--require-reviewed fails any shown overlay or recap whose non-English text has not been human reviewed.

Exit code 0 when everything passes, 1 otherwise.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

import stats_ref as S

ROOT = Path(__file__).parent
SCHEMA_DIR = ROOT / "schemas"
URN = "urn:receipts:schema:v1:"

EVENT_TYPE_TO_DEF = {
    "match_metadata": "MatchMetadataEvent",
    "period_start": "PeriodStartEvent",
    "period_end": "PeriodEndEvent",
    "pass": "PassEvent",
    "shot": "ShotEvent",
    "tackle": "TackleEvent",
    "possession_change": "PossessionChangeEvent",
    "pressure": "PressureEvent",
    "foul": "FoulEvent",
    "card": "CardEvent",
    "substitution": "SubstitutionEvent",
    "tracking_frame": "TrackingFrameEvent",
}


OVERLAY_KIND_TO_DEF = {
    "lower_third": "LowerThirdOverlay",
    "stat_card": "StatCardOverlay",
    "momentum_bar": "MomentumBarOverlay",
    "player_tag": "PlayerTagOverlay",
}

# Overlay policy v1 (see README). Changing these is a policy change, not a schema change.
CAPACITY = {"lower_third": 1, "stat_card": 1, "momentum_bar": 1, "player_tag": 3}
MAX_QUEUE_DELAY_MS = {"lower_third": 8000, "stat_card": 8000, "momentum_bar": 3000, "player_tag": 2000}
LATENCY_ROUNDING_MS = 2
DENSITY_MIN_PRIORITY = {"minimal": 70, "standard": 40, "rich": 0}
SNAPSHOT_TOLERANCE = 6e-5   # values are rounded to 4 dp

_COMMON = json.loads((SCHEMA_DIR / "common.schema.json").read_text(encoding="utf-8"))
METRIC_UNITS = _COMMON["x-metric-units"]
FAILURE_CODE_CHECKS = _COMMON["x-failure-code-checks"]    # failure code -> checks allowed to report it
CORRUPTION_OPERATORS = _COMMON["x-corruption-operators"]  # operator -> primary failure code
METRIC_SCOPE = _COMMON["x-metric-scope"]                  # metric -> allowed subject types

# Codes the deterministic layer must catch by itself: a label carrying one must make check_claims complain.
DETERMINISTIC_CODES = {
    "future_leak": "future leak",
    "evidence_not_found": "not in stream",
    "causal_order_violation": "causal order violation",
}


def _load_registry() -> Registry:
    resources = []
    for p in sorted(SCHEMA_DIR.glob("*.schema.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


REGISTRY = _load_registry()


def validator_for(ref: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": ref}, registry=REGISTRY, format_checker=FormatChecker())


def _fmt(errors) -> list[str]:
    out = []
    for e in sorted(errors, key=lambda e: [str(p) for p in e.absolute_path]):
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        out.append(f"{path}: {e.message[:200]}")
    return out


# ------------------------------------------------------------------ schema level
def validate_event(event: dict) -> list[str]:
    """Validate against the variant for its `type` so errors point at the real problem."""
    t = event.get("type") if isinstance(event, dict) else None
    if t not in EVENT_TYPE_TO_DEF:
        return [f"type: unknown event type {t!r}"]
    return _fmt(validator_for(f"{URN}event#/$defs/{EVENT_TYPE_TO_DEF[t]}").iter_errors(event))


def validate_claim(claim: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}claim").iter_errors(claim))


def validate_verdict(verdict: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}verdict").iter_errors(verdict))


def validate_eval_label(label: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}eval-label").iter_errors(label))


def validate_eval_manifest(manifest: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}eval-manifest").iter_errors(manifest))


def validate_snapshot(doc: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}snapshot").iter_errors(doc))


def validate_profile(doc: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}profile").iter_errors(doc))


def validate_match_state(doc: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}match-state").iter_errors(doc))


def validate_recap(doc: dict) -> list[str]:
    return _fmt(validator_for(f"{URN}recap").iter_errors(doc))


def validate_overlay(overlay: dict) -> list[str]:
    k = overlay.get("kind") if isinstance(overlay, dict) else None
    if k not in OVERLAY_KIND_TO_DEF:
        return [f"kind: unknown overlay kind {k!r}"]
    return _fmt(validator_for(f"{URN}overlay#/$defs/{OVERLAY_KIND_TO_DEF[k]}").iter_errors(overlay))


# ------------------------------------------------------------------ semantic level
def check_event_stream(events: list[dict]) -> list[str]:
    errs: list[str] = []
    if not events:
        return ["stream is empty"]
    first = events[0]
    if first.get("type") != "match_metadata":
        return ["seq 1 must be match_metadata"]

    meta = first["payload"]
    teams = {t["team_id"] for t in meta["teams"]}
    if {t["side"] for t in meta["teams"]} != {"home", "away"}:
        errs.append("metadata: teams must be exactly one home and one away")
    roster = {p["player_id"]: p["team_id"] for p in meta["players"]}
    if len(roster) != len(meta["players"]):
        errs.append("metadata: duplicate player_id in roster")
    for p in meta["players"]:
        if p["team_id"] not in teams:
            errs.append(f"metadata: player {p['player_id']} on unknown team {p['team_id']}")
    for tid in teams:
        if sum(1 for p in meta["players"] if p["team_id"] == tid and p["starter"]) != 11:
            errs.append(f"metadata: team {tid} must have exactly 11 starters")

    prev_time = 0
    for i, e in enumerate(events, start=1):
        loc = f"seq {e.get('seq')}"
        if e["seq"] != i:
            errs.append(f"{loc}: expected seq {i} (gapless, starting at 1)")
        if e["event_id"] != f"ev_{i:07d}":
            errs.append(f"{loc}: event_id {e['event_id']} does not match seq")
        if e["match_id"] != first["match_id"]:
            errs.append(f"{loc}: match_id differs from stream")
        if e["type"] == "match_metadata" and i != 1:
            errs.append(f"{loc}: match_metadata only allowed at seq 1")
        if e["match_time_ms"] < prev_time:
            errs.append(f"{loc}: match_time_ms goes backwards ({e['match_time_ms']} < {prev_time})")
        prev_time = max(prev_time, e["match_time_ms"])

        if "team_id" in e and e["team_id"] not in teams:
            errs.append(f"{loc}: unknown team_id {e['team_id']}")
        if "player_id" in e:
            if e["player_id"] not in roster:
                errs.append(f"{loc}: unknown player_id {e['player_id']}")
            elif "team_id" in e and roster[e["player_id"]] != e["team_id"]:
                errs.append(f"{loc}: player {e['player_id']} does not belong to team {e['team_id']}")

        pl = e["payload"]
        for key in ("receiver_id", "goalkeeper_id", "tackled_player_id", "target_player_id",
                    "fouled_player_id", "player_off_id", "player_on_id"):
            ref = pl.get(key)
            if ref is not None and ref not in roster:
                errs.append(f"{loc}: payload.{key} references unknown player {ref}")
        if pl.get("previous_team_id") is not None and pl["previous_team_id"] not in teams:
            errs.append(f"{loc}: payload.previous_team_id unknown")
        if e["type"] == "tracking_frame":
            ids = [p["player_id"] for p in pl["players"]]
            if len(ids) != len(set(ids)):
                errs.append(f"{loc}: duplicate player in tracking frame")
            for pid in ids:
                if pid not in roster:
                    errs.append(f"{loc}: tracking frame has unknown player {pid}")
        if e["type"] == "shot":
            a = pl.get("assist_event_id")
            if a is not None and int(a[3:]) >= i:
                errs.append(f"{loc}: assist_event_id must reference an earlier event")
    return errs


def _window_of(assertion: dict):
    if assertion["kind"] == "metric_trend":
        return assertion["comparison_window"]
    return assertion.get("window")


def _windows_of(assertion: dict):
    if assertion["kind"] == "metric_trend":
        return [assertion["baseline_window"], assertion["comparison_window"]]
    w = assertion.get("window")
    return [w] if w else []


def check_claims(claims: list[dict], events: list[dict], snapshots: list[dict] | None = None) -> list[str]:
    errs: list[str] = []
    by_id = {e["event_id"]: e for e in events}
    max_seq = len(events)
    claims_by_id: dict[str, dict] = {}
    for c in claims:
        if c["claim_id"] in claims_by_id:
            errs.append(f"{c['claim_id']}: duplicate claim_id")
        claims_by_id[c["claim_id"]] = c

    for c in claims:
        cid = c["claim_id"]
        if c["match_id"] != events[0]["match_id"]:
            errs.append(f"{cid}: match_id differs from stream")
        a_seq = c["as_of_seq"]
        if a_seq > max_seq:
            errs.append(f"{cid}: as_of_seq {a_seq} is beyond the stream ({max_seq})")
            continue
        as_of_time = events[a_seq - 1]["match_time_ms"]

        langs = [r["lang"] for r in c["renderings"]]
        if len(langs) != len(set(langs)):
            errs.append(f"{cid}: duplicate rendering lang")

        for ev in c["evidence"]:
            if ev["kind"] == "event":
                e = by_id.get(ev["event_id"])
                if e is None:
                    errs.append(f"{cid}: evidence {ev['event_id']} not in stream")
                elif e["seq"] > a_seq:
                    errs.append(f"{cid}: evidence {ev['event_id']} is newer than as_of_seq {a_seq} (future leak)")
            elif ev["kind"] == "seq_range":
                if ev["from_seq"] > ev["to_seq"]:
                    errs.append(f"{cid}: seq_range from_seq > to_seq")
                if ev["to_seq"] > a_seq:
                    errs.append(f"{cid}: seq_range to_seq {ev['to_seq']} is newer than as_of_seq {a_seq} (future leak)")
            elif ev["kind"] == "metric_snapshot" and ev["as_of_seq"] > a_seq:
                errs.append(f"{cid}: metric_snapshot as_of_seq {ev['as_of_seq']} is newer than claim as_of_seq (future leak)")

        if snapshots is not None:
            snaps = {x["snapshot_id"]: x for x in snapshots}
            for ev in c["evidence"]:
                if ev["kind"] != "metric_snapshot":
                    continue
                sn = snaps.get(ev["snapshot_id"])
                if sn is None:
                    errs.append(f"{cid}: cites unknown snapshot {ev['snapshot_id']}")
                    continue
                if sn["as_of_seq"] != ev["as_of_seq"]:
                    errs.append(f"{cid}: evidence as_of_seq {ev['as_of_seq']} differs from the snapshot's {sn['as_of_seq']}")
                if sn["as_of_seq"] > a_seq:
                    errs.append(f"{cid}: snapshot {sn['snapshot_id']} is newer than as_of_seq {a_seq} (future leak)")
                a = c["assertion"]
                if a["kind"] == "metric_value":
                    ent = next((e for e in sn["entities"] if e["subject"] == a["subject"]), None)
                    val = ent["metrics"].get(a["metric"]) if ent else None
                    if val is None:
                        errs.append(f"{cid}: snapshot {sn['snapshot_id']} has no {a['metric']} for the claim's subject")
                    else:
                        if sn["window"] != a["window"]:
                            errs.append(f"{cid}: snapshot window differs from the claim window")
                        if not _satisfies(a["op"], val, a["value"], a.get("tolerance")):
                            errs.append(f"{cid}: snapshot value {val} contradicts the assertion ({a['op']} {a['value']})")

        for w in _windows_of(c["assertion"]):
            if w["from_ms"] >= w["to_ms"]:
                errs.append(f"{cid}: window from_ms must be < to_ms")
            if w["to_ms"] > as_of_time:
                errs.append(f"{cid}: window ends at {w['to_ms']} ms, after the as_of event time {as_of_time} ms")

        if "supersedes" in c:
            old = claims_by_id.get(c["supersedes"])
            if old is not None and old["as_of_seq"] > a_seq:
                errs.append(f"{cid}: supersedes a claim with a later as_of_seq")

        asr = c["assertion"]
        if asr["kind"] == "causal_explanation":
            cause, effect = asr["cause_claim_id"], asr["effect_claim_id"]
            if cause == effect:
                errs.append(f"{cid}: cause and effect must differ")
            if set(c["depends_on"]) != {cause, effect}:
                errs.append(f"{cid}: depends_on must equal {{cause_claim_id, effect_claim_id}}")
            cc, ec = claims_by_id.get(cause), claims_by_id.get(effect)
            if cc is None or ec is None:
                errs.append(f"{cid}: cause or effect claim not found")
            else:
                cw, ew = _window_of(cc["assertion"]), _window_of(ec["assertion"])
                if cw and ew and cw["to_ms"] > ew["to_ms"]:
                    errs.append(f"{cid}: cause window ends after effect window (causal order violation)")
                if max(cc["as_of_seq"], ec["as_of_seq"]) > a_seq:
                    errs.append(f"{cid}: as_of_seq earlier than the claims it depends on")
    return errs


def check_verdicts(verdicts: list[dict], claims: list[dict]) -> list[str]:
    errs: list[str] = []
    claim_ids = {c["claim_id"] for c in claims}
    seen: set[str] = set()
    for v in verdicts:
        if v["verdict_id"] in seen:
            errs.append(f"{v['verdict_id']}: duplicate verdict_id")
        seen.add(v["verdict_id"])
        if v["claim_id"] not in claim_ids:
            errs.append(f"{v['verdict_id']}: references unknown claim {v['claim_id']}")
    return errs


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _satisfies(op: str, observed: float, value: float, tol: float | None) -> bool:
    eps = 1e-9
    return {
        "eq": abs(observed - value) <= eps,
        "approx": abs(observed - value) <= (tol or 0) + eps,
        "gt": observed > value,
        "gte": observed >= value - eps,
        "lt": observed < value,
        "lte": observed <= value + eps,
    }[op]


def check_overlays(overlays: list[dict], claims: list[dict], events: list[dict], verdicts: list[dict],
                   require_reviewed: bool = False, snapshots: list[dict] | None = None,
                   profiles: list[dict] | None = None) -> list[str]:
    errs: list[str] = []
    claims_by_id = {c["claim_id"]: c for c in claims}
    superseded = {c["supersedes"] for c in claims if "supersedes" in c}
    latest: dict[str, dict] = {}
    for v in verdicts:
        cur = latest.get(v["claim_id"])
        if cur is None or (v["attempt"], v["verdict_id"]) > (cur["attempt"], cur["verdict_id"]):
            latest[v["claim_id"]] = v

    by_id: dict[str, dict] = {}
    for o in overlays:
        if o["overlay_id"] in by_id:
            errs.append(f"{o['overlay_id']}: duplicate overlay_id")
        by_id[o["overlay_id"]] = o
    teams = {t["team_id"] for t in events[0]["payload"]["teams"]}
    shown = ("scheduled", "preempted")
    snaps = {x["snapshot_id"]: x for x in snapshots} if snapshots is not None else None
    profs = {x["profile_id"]: x for x in profiles} if profiles is not None else None

    def end_of(o):
        end = o["timing"]["start_ms"] + o["timing"]["duration_ms"]
        if o["disposition"] == "preempted":
            d = by_id.get(o["displaced_by"])
            if d is not None:
                end = min(end, d["timing"]["start_ms"])
        return end

    kept = [o for o in overlays if o["disposition"] in shown]

    for o in overlays:
        oid, kind, disp = o["overlay_id"], o["kind"], o["disposition"]
        t = o["timing"]
        if o["match_id"] != events[0]["match_id"]:
            errs.append(f"{oid}: match_id differs from stream")
        if t["trigger_seq"] > len(events):
            errs.append(f"{oid}: trigger_seq {t['trigger_seq']} is beyond the stream")
            continue
        trig = events[t["trigger_seq"] - 1]
        delay = t["start_ms"] - trig["match_time_ms"]
        if delay < 0:
            errs.append(f"{oid}: starts {-delay} ms before its trigger event happened")

        cids = o["source"]["claim_ids"]
        cited = []
        for cid in cids:
            c = claims_by_id.get(cid)
            if c is None:
                errs.append(f"{oid}: cites unknown claim {cid}")
                continue
            cited.append(c)
            if c["as_of_seq"] > t["trigger_seq"]:
                errs.append(f"{oid}: trigger_seq is earlier than as_of_seq of {cid}")

        unverified = [cid for cid in cids if latest.get(cid, {}).get("status") != "verified"]
        stale_claims = [cid for cid in cids if cid in superseded]

        if disp in shown:
            if delay > MAX_QUEUE_DELAY_MS[kind]:
                errs.append(f"{oid}: starts {delay} ms after its trigger, over the {kind} limit of {MAX_QUEUE_DELAY_MS[kind]} ms")
            for cid in unverified:
                errs.append(f"{oid}: shown but {cid} has no verified verdict")
            for cid in stale_claims:
                errs.append(f"{oid}: shown but {cid} has been superseded by a rewrite")
        if disp == "dropped":
            reason = o["drop_reason"]
            if reason == "unverified" and not unverified:
                errs.append(f"{oid}: drop_reason unverified but every cited claim is verified")
            if reason == "stale" and delay <= MAX_QUEUE_DELAY_MS[kind]:
                errs.append(f"{oid}: drop_reason stale but delay {delay} ms is within the limit")
            if reason == "collision":
                occupants = [k for k in kept if k["kind"] == kind
                             and k["timing"]["start_ms"] <= t["start_ms"] < end_of(k)]
                if len(occupants) < CAPACITY[kind]:
                    errs.append(f"{oid}: drop_reason collision but {kind} has free capacity at {t['start_ms']} ms")
                elif any(k["priority"] < o["priority"] for k in occupants):
                    errs.append(f"{oid}: dropped for collision although it outranks a current {kind}")
        if disp == "preempted":
            d = by_id.get(o["displaced_by"])
            if d is None:
                errs.append(f"{oid}: displaced_by {o['displaced_by']} not found")
            else:
                if d["kind"] != kind:
                    errs.append(f"{oid}: displaced_by must be the same kind")
                if d["disposition"] not in shown:
                    errs.append(f"{oid}: displaced_by must itself be shown")
                if not (t["start_ms"] < d["timing"]["start_ms"] < t["start_ms"] + t["duration_ms"]):
                    errs.append(f"{oid}: displacer must start during this overlay")
                if d["priority"] < o["priority"]:
                    errs.append(f"{oid}: displaced by a lower-priority overlay")

        # ---- payload against sources
        p = o["payload"]
        if kind == "lower_third":
            if cited:
                rend = next((r for r in cited[0]["renderings"] if r["lang"] == o["lang"]), None)
                if rend is None:
                    errs.append(f"{oid}: claim {cited[0]['claim_id']} has no {o['lang']} rendering")
                else:
                    if p["text"] != rend["text"]:
                        errs.append(f"{oid}: text differs from the claim's {o['lang']} rendering")
                    if require_reviewed and disp in shown and o["lang"] != "en" and not rend["human_reviewed"]:
                        errs.append(f"{oid}: {o['lang']} text is not human reviewed")
        elif kind == "stat_card":
            if set(cids) != {m["claim_id"] for m in p["metrics"]}:
                errs.append(f"{oid}: source.claim_ids must equal the claims behind the metrics")
            for m in p["metrics"]:
                c = claims_by_id.get(m["claim_id"])
                if c is None:
                    continue
                a = c["assertion"]
                if a["kind"] != "metric_value":
                    errs.append(f"{oid}: {m['claim_id']} is not a metric_value claim")
                    continue
                if a["subject"] != m["subject"] or a["metric"] != m["metric"]:
                    errs.append(f"{oid}: metric entry does not match the subject/metric of {m['claim_id']}")
                if METRIC_UNITS[m["metric"]] != m["unit"]:
                    errs.append(f"{oid}: unit {m['unit']} is wrong for {m['metric']} (expected {METRIC_UNITS[m['metric']]})")
                if not _satisfies(a["op"], m["value"], a["value"], a.get("tolerance")):
                    errs.append(f"{oid}: value {m['value']} violates the claim ({a['op']} {a['value']})")
        elif kind == "momentum_bar":
            w = p["window"]
            if w["from_ms"] >= w["to_ms"]:
                errs.append(f"{oid}: window from_ms must be < to_ms")
            if w["to_ms"] > trig["match_time_ms"]:
                errs.append(f"{oid}: window ends after the trigger event (future data)")
            ids = [v["team_id"] for v in p["values"]]
            if len(set(ids)) != 2 or not set(ids) <= teams:
                errs.append(f"{oid}: values must cover the two teams of the match exactly once")
        elif kind == "player_tag":
            ind = p["indicator"]
            if ind is not None:
                if "snapshot_id" not in o["source"]:
                    errs.append(f"{oid}: an indicator needs a snapshot_id")
                if ind["observed"] < ind["threshold"]:
                    errs.append(f"{oid}: indicator observed {ind['observed']} is below its threshold {ind['threshold']}")

        # ---- snapshots and profiles
        sid = o["source"].get("snapshot_id")
        sn = None
        if sid and snaps is not None:
            sn = snaps.get(sid)
            if sn is None:
                errs.append(f"{oid}: cites unknown snapshot {sid}")
            elif sn["as_of_seq"] > t["trigger_seq"]:
                errs.append(f"{oid}: snapshot {sid} is newer than trigger_seq")

        def _snap_value(subject, metric):
            ent = next((x for x in sn["entities"] if x["subject"] == subject), None) if sn else None
            return ent["metrics"].get(metric) if ent else None

        if kind == "momentum_bar" and sn is not None:
            if sn["window"] != p["window"]:
                errs.append(f"{oid}: window differs from snapshot {sid}")
            for v in p["values"]:
                sv = _snap_value({"entity_type": "team", "entity_id": v["team_id"]}, p["metric"])
                if sv is None or abs(sv - v["value"]) > SNAPSHOT_TOLERANCE:
                    errs.append(f"{oid}: {p['metric']} for {v['team_id']} is {v['value']} but snapshot {sid} has {sv}")
        if kind == "player_tag" and p["indicator"] is not None:
            ind = p["indicator"]
            if ind["metric"] == "speed_kmh" and trig["type"] == "tracking_frame":
                fp = next((q for q in trig["payload"]["players"] if q["player_id"] == p["player_id"]), None)
                if fp is not None and abs(fp["speed_kmh"] - ind["observed"]) > 1e-9:
                    errs.append(f"{oid}: observed speed {ind['observed']} differs from the trigger frame ({fp['speed_kmh']})")
            if ind["metric"] == "distance_km" and sn is not None:
                sv = _snap_value({"entity_type": "player", "entity_id": p["player_id"]}, "distance_km")
                if sv is None or abs(sv - ind["observed"]) > SNAPSHOT_TOLERANCE:
                    errs.append(f"{oid}: observed distance {ind['observed']} differs from snapshot {sid} ({sv})")
        if o.get("profile_id") and profs is not None:
            pr = profs.get(o["profile_id"])
            if pr is None:
                errs.append(f"{oid}: unknown profile {o['profile_id']}")
            else:
                if pr["lang"] != o["lang"]:
                    errs.append(f"{oid}: lang {o['lang']} differs from profile {pr['profile_id']} ({pr['lang']})")
                if disp in shown and o["priority"] < DENSITY_MIN_PRIORITY[pr["density"]]:
                    errs.append(f"{oid}: priority {o['priority']} is below the {pr['density']} density floor "
                                f"({DENSITY_MIN_PRIORITY[pr['density']]}) of {pr['profile_id']}")

        # ---- latency measurement point
        lat = o.get("latency")
        if lat:
            ee = trig.get("emitted_at")
            if ee is not None and _ts(ee) != _ts(lat["event_emitted_at"]):
                errs.append(f"{oid}: latency.event_emitted_at differs from the trigger event's emitted_at")
            total = (_ts(lat["compiled_at"]) - _ts(lat["event_emitted_at"])).total_seconds() * 1000
            if total < 0:
                errs.append(f"{oid}: compiled_at is before event_emitted_at")
            elif sum(lat["stages_ms"].values()) > total + LATENCY_ROUNDING_MS:
                errs.append(f"{oid}: stages sum to {sum(lat['stages_ms'].values())} ms but event-to-overlay was {total:.0f} ms")

    # ---- capacity sweep per kind (kept overlays only)
    for kind, cap in CAPACITY.items():
        marks = []
        for o in kept:
            if o["kind"] == kind:
                marks.append((o["timing"]["start_ms"], 1, o["overlay_id"]))
                marks.append((end_of(o), -1, o["overlay_id"]))
        live = 0
        for ms, delta, oid in sorted(marks, key=lambda m: (m[0], m[1])):
            live += delta
            if live > cap:
                errs.append(f"{oid}: {kind} capacity {cap} exceeded at {ms} ms")
                break
    return errs


# ------------------------------------------------------------------ shared state
def _latest_verdicts(verdicts: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for v in verdicts:
        cur = latest.get(v["claim_id"])
        if cur is None or (v["attempt"], v["verdict_id"]) > (cur["attempt"], cur["verdict_id"]):
            latest[v["claim_id"]] = v
    return latest


def eligible_claims(claims: list[dict], verdicts: list[dict], as_of_seq: int) -> list[dict]:
    """Verified, not superseded, and knowable at as_of_seq. Best first: salience descending, then claim id."""
    latest = _latest_verdicts(verdicts)
    superseded = {c["supersedes"] for c in claims if "supersedes" in c}
    ok = [c for c in claims if latest.get(c["claim_id"], {}).get("status") == "verified"
          and c["claim_id"] not in superseded and c["as_of_seq"] <= as_of_seq]
    return sorted(ok, key=lambda c: (-c["salience"], c["claim_id"]))


def check_snapshots(snapshots: list[dict], events: list[dict]) -> list[str]:
    """Recompute every value with the reference stats engine."""
    errs: list[str] = []
    meta = events[0]["payload"]
    teams = {t["team_id"] for t in meta["teams"]}
    roster = {p["player_id"] for p in meta["players"]}
    seen: set[str] = set()
    for sn in snapshots:
        sid = sn["snapshot_id"]
        if sid in seen:
            errs.append(f"{sid}: duplicate snapshot_id")
        seen.add(sid)
        if sn["match_id"] != events[0]["match_id"]:
            errs.append(f"{sid}: match_id differs from stream")
        a = sn["as_of_seq"]
        if a > len(events):
            errs.append(f"{sid}: as_of_seq {a} is beyond the stream")
            continue
        w = sn["window"]
        if w["from_ms"] >= w["to_ms"]:
            errs.append(f"{sid}: window from_ms must be < to_ms")
        if w["to_ms"] > events[a - 1]["match_time_ms"]:
            errs.append(f"{sid}: window ends after the as_of event (future data)")
        if sn["stats_engine_version"] != S.STATS_ENGINE_VERSION:
            errs.append(f"{sid}: computed by engine {sn['stats_engine_version']}, this validator implements {S.STATS_ENGINE_VERSION}")
            continue
        ctx = S.StatsContext(events, a)
        subjects: set[tuple[str, str]] = set()
        for ent in sn["entities"]:
            subj = ent["subject"]
            key = (subj["entity_type"], subj["entity_id"])
            if key in subjects:
                errs.append(f"{sid}: duplicate subject {key[0]} {key[1]}")
            subjects.add(key)
            known = {"player": roster, "team": teams, "match": {events[0]["match_id"]}}[key[0]]
            if key[1] not in known:
                errs.append(f"{sid}: unknown {key[0]} {key[1]}")
                continue
            for metric, value in ent["metrics"].items():
                if key[0] not in METRIC_SCOPE[metric]:
                    errs.append(f"{sid}: {metric} is not defined for a {key[0]}")
                    continue
                exp = ctx.metric(subj, metric, w)
                if exp is None:
                    errs.append(f"{sid}: {metric} for {key[1]} is undefined in this window but the snapshot lists it")
                elif abs(exp - value) > SNAPSHOT_TOLERANCE:
                    errs.append(f"{sid}: {metric} for {key[1]} is {value} but the reference engine computes {exp}")
    return errs


def check_profiles(profiles: list[dict], events: list[dict]) -> list[str]:
    errs: list[str] = []
    meta = events[0]["payload"]
    teams = {t["team_id"] for t in meta["teams"]}
    roster = {p["player_id"] for p in meta["players"]}
    seen: set[str] = set()
    for p in profiles:
        pid = p["profile_id"]
        if pid in seen:
            errs.append(f"{pid}: duplicate profile_id")
        seen.add(pid)
        for t in p["favorite_team_ids"]:
            if t not in teams:
                errs.append(f"{pid}: favorite team {t} is not in this match")
        for pl in p["favorite_player_ids"]:
            if pl not in roster:
                errs.append(f"{pid}: favorite player {pl} is not in this match")
        if p["focus"]["kind"] == "player" and p["focus"]["player_id"] not in roster:
            errs.append(f"{pid}: focus player {p['focus']['player_id']} is not in this match")
    return errs


def check_match_state(state: dict, events: list[dict], claims: list[dict], verdicts: list[dict],
                      snapshots: list[dict] | None = None) -> list[str]:
    errs: list[str] = []
    if state["match_id"] != events[0]["match_id"]:
        errs.append("state: match_id differs from stream")
    a = state["as_of_seq"]
    if a > len(events):
        return errs + [f"state: as_of_seq {a} is beyond the stream"]
    now = events[a - 1]["match_time_ms"]

    status = "live"
    for e in reversed(events[:a]):
        if e["type"] == "period_end":
            status = "full_time" if e["payload"]["is_final"] else "half_time"
            break
        if e["type"] == "period_start":
            break
    if state["status"] != status:
        errs.append(f"state: status is {state['status']} but the stream says {status}")

    ctx = S.StatsContext(events, a)
    teams = {t["team_id"] for t in events[0]["payload"]["teams"]}
    if {x["team_id"] for x in state["score"]} != teams:
        errs.append("state: score must list each team exactly once")
    else:
        for x in state["score"]:
            goals = ctx.metric({"entity_type": "team", "entity_id": x["team_id"]}, "goals", {"from_ms": 0, "to_ms": now})
            if int(goals) != x["goals"]:
                errs.append(f"state: score for {x['team_id']} is {x['goals']} but the stream has {int(goals)} goals")

    ids = [m["claim_id"] for m in state["key_moments"]]
    if len(ids) != len(set(ids)):
        errs.append("state: duplicate claim in key_moments")
    if [m["rank"] for m in state["key_moments"]] != list(range(1, len(ids) + 1)):
        errs.append("state: key_moments ranks must run 1..n in order")
    expected = [c["claim_id"] for c in eligible_claims(claims, verdicts, a)][:12]
    if ids != expected:
        errs.append(f"state: key_moments {ids} is not the top of the eligible claims {expected}")

    if snapshots is not None:
        sn = next((x for x in snapshots if x["snapshot_id"] == state["snapshot_id"]), None)
        if sn is None:
            errs.append(f"state: snapshot {state['snapshot_id']} not found")
        else:
            if sn["as_of_seq"] != a:
                errs.append("state: snapshot as_of_seq differs from the state's")
            if sn["window"] != {"from_ms": 0, "to_ms": now}:
                errs.append(f"state: snapshot window must be 0 to {now} ms")
    return errs


def check_recap(recap: dict, claims: list[dict], verdicts: list[dict], events: list[dict],
                state: dict | None = None, profiles: list[dict] | None = None,
                require_reviewed: bool = False) -> list[str]:
    errs: list[str] = []
    if recap["match_id"] != events[0]["match_id"]:
        errs.append("recap: match_id differs from stream")
    a = recap["as_of_seq"]
    if a > len(events):
        return errs + [f"recap: as_of_seq {a} is beyond the stream"]
    by_id = {c["claim_id"]: c for c in claims}
    ok = {c["claim_id"] for c in eligible_claims(claims, verdicts, a)}
    used: set[str] = set()
    for i, sec in enumerate(recap["sections"], start=1):
        parts = []
        for cid in sec["claim_ids"]:
            if cid in used:
                errs.append(f"recap section {i}: {cid} is used twice")
            used.add(cid)
            c = by_id.get(cid)
            if c is None:
                errs.append(f"recap section {i}: unknown claim {cid}")
                continue
            if cid not in ok:
                errs.append(f"recap section {i}: {cid} is not verified, is superseded, or is newer than as_of_seq")
            rend = next((r for r in c["renderings"] if r["lang"] == recap["lang"]), None)
            if rend is None:
                errs.append(f"recap section {i}: {cid} has no {recap['lang']} rendering")
                continue
            if require_reviewed and recap["lang"] != "en" and not rend["human_reviewed"]:
                errs.append(f"recap section {i}: {recap['lang']} text of {cid} is not human reviewed")
            parts.append(rend["text"])
        if len(parts) == len(sec["claim_ids"]) and sec["text"] != " ".join(parts):
            errs.append(f"recap section {i}: text is not the cited claims' {recap['lang']} renderings joined by spaces")
    if state is not None:
        if state["as_of_seq"] != a:
            errs.append("recap: as_of_seq differs from the match state's")
        if state["status"] != recap["kind"]:
            errs.append(f"recap: kind {recap['kind']} but the match is {state['status']}")
        keyed = {m["claim_id"] for m in state["key_moments"]}
        for cid in used - keyed:
            errs.append(f"recap: {cid} is not one of the match state's key moments")
    if recap.get("profile_id") and profiles is not None:
        pr = next((p for p in profiles if p["profile_id"] == recap["profile_id"]), None)
        if pr is None:
            errs.append(f"recap: unknown profile {recap['profile_id']}")
        elif pr["lang"] != recap["lang"]:
            errs.append(f"recap: lang {recap['lang']} differs from profile {pr['profile_id']} ({pr['lang']})")
    return errs


# ------------------------------------------------------------------ eval sets
def _claim_core(claim: dict) -> dict:
    """The parts of a claim that carry meaning; ids and authorship are ignored when comparing."""
    c = copy.deepcopy(claim)
    for k in ("claim_id", "produced_by", "supersedes"):
        c.pop(k, None)
    return c


def check_eval_set(manifest: dict, labels: list[dict], streams: dict[str, list[dict]]) -> list[str]:
    errs: list[str] = []
    if manifest["label_count"] != len(labels):
        errs.append(f"manifest: label_count {manifest['label_count']} but {len(labels)} labels")
    for s in manifest["streams"]:
        n = len(streams.get(s["match_id"], []))
        if n != s["event_count"]:
            errs.append(f"manifest: stream {s['match_id']} has {n} events, manifest says {s['event_count']}")

    by_id: dict[str, dict] = {}
    claim_ids: set[str] = set()
    for l in labels:
        if l["label_id"] in by_id:
            errs.append(f"{l['label_id']}: duplicate label_id")
        by_id[l["label_id"]] = l
        cid = l["claim"]["claim_id"]
        if cid in claim_ids:
            errs.append(f"{l['label_id']}: duplicate claim_id {cid} across labels")
        claim_ids.add(cid)

    # deterministic-layer findings per claim, computed once per match
    claim_errs: dict[str, list[str]] = defaultdict(list)
    per_match: dict[str, list[dict]] = defaultdict(list)
    for l in labels:
        per_match[l["claim"]["match_id"]].append(l["claim"])
    for match, cs in per_match.items():
        if match not in streams:
            errs.append(f"labels reference match {match} which the manifest does not list")
            continue
        for e in check_claims(cs, streams[match]):
            claim_errs[e.split(":")[0]].append(e)

    for l in labels:
        lid, exp, claim = l["label_id"], l["expected"], l["claim"]
        codes, checks = set(exp["failure_codes"]), set(exp["failed_checks"])

        # expected checks must be explained by the expected codes, and vice versa
        allowed = set().union(*(set(FAILURE_CODE_CHECKS[c]) for c in codes)) if codes else set()
        for chk in checks - allowed:
            errs.append(f"{lid}: failed check {chk} is not reported by any of the expected codes")
        for c in codes:
            if not set(FAILURE_CODE_CHECKS[c]) & checks:
                errs.append(f"{lid}: expected code {c} needs one of {FAILURE_CODE_CHECKS[c]} in failed_checks")

        findings = claim_errs.get(claim["claim_id"], [])
        if exp["status"] == "verified" and findings:
            errs.append(f"{lid}: labelled verified but the deterministic checks object: {findings[0]}")
        for code, needle in DETERMINISTIC_CODES.items():
            if code in codes and not any(needle in f for f in findings):
                errs.append(f"{lid}: expects {code} but the deterministic checks do not see it")
        if "translation_drift" in codes and not any(r["origin"] == "translated" for r in claim["renderings"]):
            errs.append(f"{lid}: translation_drift needs a translated rendering")

        if l["origin"] == "generated_corrupted":
            cor = l["corruption"]
            base = by_id.get(cor["base_label_id"])
            if base is None:
                errs.append(f"{lid}: base_label_id {cor['base_label_id']} not found")
                continue
            if base["origin"] != "generated_clean":
                errs.append(f"{lid}: base label must be generated_clean")
            if base["claim"]["match_id"] != claim["match_id"]:
                errs.append(f"{lid}: base label is from a different match")
            if base["split"] != l["split"]:
                errs.append(f"{lid}: split {l['split']} differs from its base's split {base['split']} (leakage)")
            if _claim_core(base["claim"]) == _claim_core(claim):
                errs.append(f"{lid}: corrupted claim is identical to its base")
            primary = CORRUPTION_OPERATORS[cor["operator"]]
            if primary not in codes:
                errs.append(f"{lid}: operator {cor['operator']} should provoke {primary}, which is not in expected codes")
    return errs


def load_eval_set(manifest_path: str | Path):
    """Load a manifest, its labels and streams, checking every hash. Returns (manifest, labels, streams, errors)."""
    mp = Path(manifest_path)
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    errs = [f"manifest: {m}" for m in validate_eval_manifest(manifest)]
    if errs:
        return manifest, [], {}, errs

    def resolve(rel: str) -> Path | None:
        p = (mp.parent / rel).resolve()
        return p if p.is_file() else None

    labels: list[dict] = []
    lp = resolve(manifest["labels_file"])
    if lp is None:
        errs.append(f"manifest: labels_file {manifest['labels_file']} not found")
    else:
        if hashlib.sha256(lp.read_bytes()).hexdigest() != manifest["labels_sha256"]:
            errs.append("manifest: labels_sha256 does not match the labels file")
        labels = load_jsonl(lp)

    streams: dict[str, list[dict]] = {}
    for s in manifest["streams"]:
        sp = resolve(s["file"])
        if sp is None:
            errs.append(f"manifest: stream file {s['file']} not found")
            continue
        if hashlib.sha256(sp.read_bytes()).hexdigest() != s["sha256"]:
            errs.append(f"manifest: sha256 for {s['file']} does not match")
        streams[s["match_id"]] = load_jsonl(sp)
    return manifest, labels, streams, errs


def validate_eval_set(manifest_path: str | Path) -> list[str]:
    manifest, labels, streams, errs = load_eval_set(manifest_path)
    if errs:
        return errs
    for l in labels:
        errs += [f"label {l.get('label_id')}: {m}" for m in validate_eval_label(l)]
    for match, events in streams.items():
        for e in events:
            errs += [f"stream {match} seq {e.get('seq')}: {m}" for m in validate_event(e)]
    if errs:
        return errs
    for match, events in streams.items():
        errs += [f"stream {match}: {m}" for m in check_event_stream(events)]
    return errs or check_eval_set(manifest, labels, streams)


# ------------------------------------------------------------------ io / cli
def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_all(events, claims=(), verdicts=(), overlays=(), require_reviewed=False,
                 snapshots=(), profiles=(), state=None, recap=None) -> list[str]:
    errs: list[str] = []
    for e in events:
        errs += [f"event seq {e.get('seq')}: {m}" for m in validate_event(e)]
    for c in claims:
        errs += [f"claim {c.get('claim_id')}: {m}" for m in validate_claim(c)]
    for v in verdicts:
        errs += [f"verdict {v.get('verdict_id')}: {m}" for m in validate_verdict(v)]
    for o in overlays:
        errs += [f"overlay {o.get('overlay_id')}: {m}" for m in validate_overlay(o)]
    for x in snapshots:
        errs += [f"snapshot {x.get('snapshot_id')}: {m}" for m in validate_snapshot(x)]
    for p in profiles:
        errs += [f"profile {p.get('profile_id')}: {m}" for m in validate_profile(p)]
    if state is not None:
        errs += [f"state: {m}" for m in validate_match_state(state)]
    if recap is not None:
        errs += [f"recap: {m}" for m in validate_recap(recap)]
    if errs:  # semantic checks assume schema-valid input
        return errs
    events, claims, verdicts = list(events), list(claims), list(verdicts)
    snaps = list(snapshots) or None
    profs = list(profiles) or None
    errs += check_event_stream(events)
    if snapshots:
        errs += check_snapshots(list(snapshots), events)
    if profiles:
        errs += check_profiles(list(profiles), events)
    if claims:
        errs += check_claims(claims, events, snaps)
    if verdicts:
        errs += check_verdicts(verdicts, claims)
    if overlays:
        errs += check_overlays(list(overlays), claims, events, verdicts, require_reviewed, snaps, profs)
    if state is not None:
        errs += check_match_state(state, events, claims, verdicts, snaps)
    if recap is not None:
        errs += check_recap(recap, claims, verdicts, events, state, profs, require_reviewed)
    return errs


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Validate Receipts documents against the v1 contracts.")
    ap.add_argument("events", nargs="?", help="match event stream (JSONL)")
    ap.add_argument("--claims"), ap.add_argument("--verdicts"), ap.add_argument("--overlays")
    ap.add_argument("--snapshots"), ap.add_argument("--profiles"), ap.add_argument("--state"), ap.add_argument("--recap")
    ap.add_argument("--eval", metavar="MANIFEST", help="validate an eval set instead")
    ap.add_argument("--require-reviewed", action="store_true",
                    help="fail any shown overlay or recap whose non-English text is not human reviewed")
    args = ap.parse_args(argv)
    if args.eval:
        errs = validate_eval_set(args.eval)
        for m in errs:
            print("FAIL", m)
        if not errs:
            manifest, labels, _, _ = load_eval_set(args.eval)
            print(f"OK: eval set {manifest['set_id']} v{manifest['set_version']}, {len(labels)} labels")
        return 1 if errs else 0
    if not args.events:
        ap.print_help()
        return 2
    events = load_jsonl(args.events)
    docs = dict(
        claims=_load_json(args.claims) if args.claims else [],
        verdicts=_load_json(args.verdicts) if args.verdicts else [],
        overlays=load_jsonl(args.overlays) if args.overlays else [],
        snapshots=_load_json(args.snapshots) if args.snapshots else [],
        profiles=_load_json(args.profiles) if args.profiles else [],
        state=_load_json(args.state) if args.state else None,
        recap=_load_json(args.recap) if args.recap else None,
    )
    errs = validate_all(events, require_reviewed=args.require_reviewed, **docs)
    for m in errs:
        print("FAIL", m)
    if not errs:
        counts = ", ".join(f"{len(v)} {k}" for k, v in docs.items() if isinstance(v, list) and v)
        extra = ", ".join(k for k in ("state", "recap") if docs[k] is not None)
        print(f"OK: {len(events)} events" + (f", {counts}" if counts else "") + (f", {extra}" if extra else ""))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
