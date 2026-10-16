"""Writes examples/eval/labels.jsonl and examples/eval/manifest.json.

Clean labels come from the valid claims. Corrupted labels apply one small operator to a clean label.
The operators here are the seed of the real mutator: each changes exactly one thing and keeps the
claim schema-valid, so the Verifier (not the schema) has to catch it.
"""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALID = ROOT / "examples" / "valid"
OUT = ROOT / "examples" / "eval"
OUT.mkdir(parents=True, exist_ok=True)

claims = {c["claim_id"]: c for c in json.loads((VALID / "claims.json").read_text(encoding="utf-8"))}


def derive(base, new_id, **mods):
    """Copy a claim under a new id, as if the Narrator had produced it."""
    c = copy.deepcopy(base)
    c["claim_id"] = new_id
    c.pop("supersedes", None)
    c["produced_by"] = {"agent": "narrator", "run_id": "run_mutator01", "agent_version": "0.1.0"}
    for k, v in mods.items():
        c[k] = v
    return c


def label(n, split, origin, difficulty, claim, expected, corruption=None):
    out = {"schema_version": "1.0.0", "label_id": f"lb_{n:07d}", "split": split, "origin": origin,
           "difficulty": difficulty, "claim": claim}
    if corruption:
        out["corruption"] = corruption
    out["expected"] = expected
    return out


OK = {"status": "verified", "failure_codes": [], "failed_checks": []}


def bad(code, check, rewritable=True):
    return {"status": "rejected", "failure_codes": [code], "failed_checks": [check], "rewritable": rewritable}


def corr(operator, base_n, detail):
    return {"operator": operator, "base_label_id": f"lb_{base_n:07d}", "detail": detail}


cl1, cl2, cl3, cl4, cl5 = (claims[f"cl_000000{i}"] for i in range(1, 6))

rows = []
# ---- clean (generated from the valid fixtures)
rows.append(label(1, "dev", "generated_clean", "obvious", cl1, OK))
rows.append(label(2, "dev", "generated_clean", "obvious", cl2, OK))
rows.append(label(3, "test", "generated_clean", "obvious", cl3, OK))
rows.append(label(4, "test", "generated_clean", "obvious", cl5, OK))

# ---- corrupted (one operator each; split follows the base label)
c = derive(cl1, "cl_0000101")
c["assertion"]["value"] = 0.46
for r in c["renderings"]:
    r["text"] = r["text"].replace("0.31", "0.46")
rows.append(label(5, "dev", "generated_corrupted", "obvious", c, bad("wrong_value", "assertion_numeric_match"),
                  corr("perturb_value", 1, "xG value 0.31 -> 0.46 in assertion and both renderings")))

c = derive(cl2, "cl_0000102")
c["assertion"]["subject"]["entity_id"] = "p_206"
c["renderings"][0]["text"] = c["renderings"][0]["text"].replace("No. 5", "No. 6")
rows.append(label(6, "dev", "generated_corrupted", "obvious", c, bad("wrong_player", "evidence_supports_assertion"),
                  corr("swap_player", 2, "pressing player p_205 -> p_206; evidence still shows p_205")))

c = derive(cl3, "cl_0000103")
c["assertion"]["window"] = {"from_ms": 2000, "to_ms": 3000}
rows.append(label(7, "test", "generated_corrupted", "obvious", c, bad("wrong_time_window", "evidence_supports_assertion"),
                  corr("shift_window", 3, "window 6000-6100 -> 2000-3000; the cited events are outside it")))

c = derive(cl2, "cl_0000104")
c["evidence"].append({"kind": "event", "event_id": "ev_0000015", "role": "context"})
rows.append(label(8, "dev", "generated_corrupted", "obvious", c, bad("future_leak", "evidence_within_as_of"),
                  corr("cite_future_event", 2, "added ev_0000015 (seq 15) to a claim with as_of_seq 8")))

c = derive(cl5, "cl_0000105", as_of_seq=15, depends_on=["cl_0000003", "cl_0000001"])
c["assertion"] = {"kind": "causal_explanation", "cause_claim_id": "cl_0000003", "effect_claim_id": "cl_0000001",
                  "mechanism": "Winning the ball back led directly to Northgate's chance."}
c["renderings"] = [{"lang": "en", "text": "That tackle is why Northgate got their 0.31 xG chance.",
                    "origin": "authored", "human_reviewed": False}]
rows.append(label(9, "test", "generated_corrupted", "subtle", c, bad("unsupported_causal", "causal_plausibility", False),
                  corr("invent_causal_link", 4, "linked two true claims in the right order with no supported mechanism")))

c = derive(cl5, "cl_0000106", as_of_seq=15, depends_on=["cl_0000001", "cl_0000003"])
c["assertion"] = {"kind": "causal_explanation", "cause_claim_id": "cl_0000001", "effect_claim_id": "cl_0000003",
                  "mechanism": "Northgate's chance set up the tackle that won possession."}
c["renderings"] = [{"lang": "en", "text": "Northgate's early chance is why Aldermoor won the ball back.",
                    "origin": "authored", "human_reviewed": False}]
rows.append(label(10, "test", "generated_corrupted", "obvious", c, bad("causal_order_violation", "causal_precedence"),
                  corr("reverse_causal_order", 4, "cause and effect swapped; the cause window ends after the effect window")))

c = derive(cl1, "cl_0000107")
c["renderings"][0]["text"] = "Northgate's first chance, 20 seconds in, carried 0.31 xG, the best of the half."
rows.append(label(11, "dev", "generated_corrupted", "subtle", c, bad("rendering_adds_detail", "rendering_entails_assertion"),
                  corr("embellish_rendering", 1, "added 'the best of the half', which no evidence supports")))

c = derive(cl1, "cl_0000108")
c["renderings"][1]["text"] = c["renderings"][1]["text"].replace("0.31", "0.13")
rows.append(label(12, "dev", "generated_corrupted", "subtle", c, bad("translation_drift", "translation_fidelity"),
                  corr("drift_translation", 1, "sw rendering digits swapped: 0.31 -> 0.13")))

# ---- hand written: a false-positive trap and a known rewrite case
c = derive(cl1, "cl_0000109")
c["assertion"]["value"] = 0.3149   # inside the 0.005 tolerance of the true 0.31
c["renderings"] = [{"lang": "en", "text": "Northgate's first chance, 20 seconds in, was worth roughly 0.31 xG.",
                    "origin": "authored", "human_reviewed": False}]
rows.append(label(13, "test", "hand_written", "subtle", c, OK))
rows.append(label(14, "dev", "hand_written", "subtle", copy.deepcopy(cl4), bad("rendering_adds_detail", "rendering_entails_assertion")))

labels_path = OUT / "labels.jsonl"
labels_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

stream_path = VALID / "match_stream.jsonl"
stream_bytes = stream_path.read_bytes()
manifest = {
    "schema_version": "1.0.0",
    "set_id": "evalset_demo",
    "set_version": "0.1.0",
    "labels_file": "labels.jsonl",
    "labels_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
    "label_count": len(rows),
    "streams": [{
        "match_id": "ngt-ald-demo01",
        "file": "../valid/match_stream.jsonl",
        "sha256": hashlib.sha256(stream_bytes).hexdigest(),
        "event_count": stream_bytes.decode("utf-8").count("\n"),
    }],
}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"wrote {len(rows)} labels -> {labels_path}")
