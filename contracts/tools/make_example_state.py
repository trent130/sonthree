"""Writes examples/valid/{snapshots,profiles,match_state,recap}.json and wires the existing claim and
overlay fixtures to them (snapshot evidence on cl_0000001, profile ids and momentum values on overlays).

Every snapshot value comes from stats_ref, so the fixtures are exactly what the validator recomputes.
Run order: make_example_stream.py, this script, make_example_evalset.py (its manifest hashes the claims).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import stats_ref as S  # noqa: E402

VALID = ROOT / "examples" / "valid"
MATCH = "ngt-ald-demo01"
events = [json.loads(x) for x in (VALID / "match_stream.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
claims = json.loads((VALID / "claims.json").read_text(encoding="utf-8"))
verdicts = json.loads((VALID / "verdicts.json").read_text(encoding="utf-8"))


def team(t):
    return {"entity_type": "team", "entity_id": t}


def player(p):
    return {"entity_type": "player", "entity_id": p}


def snapshot(n, as_of_seq, to_ms, subjects):
    ctx = S.StatsContext(events, as_of_seq)
    w = {"from_ms": 0, "to_ms": to_ms}
    entities = []
    for subj, metrics in subjects:
        vals = {m: ctx.metric(subj, m, w) for m in metrics}
        vals = {m: v for m, v in vals.items() if v is not None}
        entities.append({"subject": subj, "metrics": vals})
    return {"schema_version": "1.0.0", "snapshot_id": f"snap_{n:07d}", "match_id": MATCH, "as_of_seq": as_of_seq,
            "stats_engine_version": S.STATS_ENGINE_VERSION, "window": w, "entities": entities}


team_metrics = ["goals", "shots", "xg", "possession_pct", "control_index", "pressures"]
snaps = [
    snapshot(1, 15, 20500, [(team("t_ngt"), team_metrics), (team("t_ald"), team_metrics)]),
    snapshot(2, 10, 8000, [(player("p_205"), ["pressures", "tackles_won", "top_speed_kmh"])]),
    snapshot(3, 15, 20500, [(team("t_ngt"), ["control_index"]), (team("t_ald"), ["control_index"])]),
    snapshot(4, 16, 2820000, [(team("t_ngt"), team_metrics + ["ppda"]), (team("t_ald"), team_metrics + ["ppda"]),
                              ({"entity_type": "match", "entity_id": MATCH}, ["max_ball_speed_kmh"])]),
]
(VALID / "snapshots.json").write_text(json.dumps(snaps, indent=2) + "\n", encoding="utf-8")

profiles = [
    {"schema_version": "1.0.0", "profile_id": "prof_analyst_en", "mode": "analyst", "lang": "en",
     "favorite_team_ids": ["t_ald"], "favorite_player_ids": [], "focus": {"kind": "metric", "metric": "pressure_index"},
     "density": "rich"},
    {"schema_version": "1.0.0", "profile_id": "prof_casual_sw", "mode": "casual", "lang": "sw",
     "favorite_team_ids": ["t_ngt"], "favorite_player_ids": ["p_110"], "focus": {"kind": "player", "player_id": "p_110"},
     "density": "minimal"},
]
(VALID / "profiles.json").write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")

# ---- match state: half time, top of the eligible claims
latest = {}
for v in verdicts:
    cur = latest.get(v["claim_id"])
    if cur is None or (v["attempt"], v["verdict_id"]) > (cur["attempt"], cur["verdict_id"]):
        latest[v["claim_id"]] = v
superseded = {c["supersedes"] for c in claims if "supersedes" in c}
eligible = sorted((c for c in claims if latest[c["claim_id"]]["status"] == "verified" and c["claim_id"] not in superseded),
                  key=lambda c: (-c["salience"], c["claim_id"]))
ctx = S.StatsContext(events, 16)
now = events[15]["match_time_ms"]
state = {
    "schema_version": "1.0.0", "match_id": MATCH, "as_of_seq": 16, "status": "half_time",
    "score": [{"team_id": t, "goals": int(ctx.metric(team(t), "goals", {"from_ms": 0, "to_ms": now}))}
              for t in ("t_ngt", "t_ald")],
    "snapshot_id": "snap_0000004",
    "key_moments": [{"claim_id": c["claim_id"], "rank": i} for i, c in enumerate(eligible, start=1)],
}
(VALID / "match_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

# ---- recap: only verified claims, text is their renderings
by_id = {c["claim_id"]: c for c in claims}


def text(*ids):
    return " ".join(next(r["text"] for r in by_id[i]["renderings"] if r["lang"] == "en") for i in ids)


recap = {
    "schema_version": "1.0.0", "recap_id": "rc_0000001", "match_id": MATCH, "kind": "half_time", "as_of_seq": 16,
    "lang": "en", "profile_id": "prof_analyst_en",
    "sections": [
        {"heading": "numbers", "claim_ids": ["cl_0000001"], "text": text("cl_0000001")},
        {"heading": "turning_point", "claim_ids": ["cl_0000002", "cl_0000005"], "text": text("cl_0000002", "cl_0000005")},
    ],
}
(VALID / "recap.json").write_text(json.dumps(recap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

# ---- wire existing fixtures to the new documents (idempotent)
ref = {"kind": "metric_snapshot", "snapshot_id": "snap_0000001", "as_of_seq": 15, "role": "context"}
c1 = by_id["cl_0000001"]
if ref not in c1["evidence"]:
    c1["evidence"].append(ref)
(VALID / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

overlays = [json.loads(x) for x in (VALID / "overlays.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
snap3 = {e["subject"]["entity_id"]: e["metrics"]["control_index"] for e in snaps[2]["entities"]}
for o in overlays:
    o["profile_id"] = "prof_analyst_en"
    if o["kind"] == "momentum_bar":
        o["payload"]["values"] = [{"team_id": t, "value": snap3[t]} for t in ("t_ngt", "t_ald")]
(VALID / "overlays.jsonl").write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in overlays) + "\n", encoding="utf-8")
print("wrote snapshots, profiles, match_state, recap; patched claims and overlays")
