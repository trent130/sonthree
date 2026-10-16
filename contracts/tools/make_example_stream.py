"""Writes examples/valid/match_stream.jsonl: a 16-event fixture that exercises every event type
used in the example claims. This is NOT the real generator; it only pins the contract."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MATCH = "ngt-ald-demo01"
HOME, AWAY = "t_ngt", "t_ald"
VER = "1.0.0"
BASE = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)  # wall clock at kick-off; the fixture streams at 1x

home_names = ["Elias Moreau", "Tomas Brandt", "Kofi Adjei", "Luca Ferrante", "Jonas Lindqvist", "Mateo Salgado",
              "Idris Okafor", "Nils Haverkamp", "Rafael Duarte", "Sami Haddad", "Viktor Osei"]
away_names = ["Oskar Lund", "Pavel Novak", "Daniel Mwangi", "Hugo Barbier", "Ali Karimi", "Emre Yildiz",
              "Stefan Marek", "Joao Teixeira", "Ben Achterberg", "Yusuf Demir", "Carlos Ibarra"]
positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "CM", "AM", "W", "ST"]
away_positions = ["GK", "CB", "CB", "FB", "DM", "FB", "CM", "CM", "AM", "W", "ST"]


def roster():
    out = []
    for base, team, names, pos in ((100, HOME, home_names, positions), (200, AWAY, away_names, away_positions)):
        for i, (n, p) in enumerate(zip(names, pos), start=1):
            out.append({"player_id": f"p_{base + i}", "team_id": team, "name": n,
                        "shirt_number": i, "position": p, "starter": True})
    return out


events = []


def add(t, period, ms, payload, **extra):
    seq = len(events) + 1
    e = {"schema_version": VER, "event_id": f"ev_{seq:07d}", "match_id": MATCH, "seq": seq,
         "type": t, "period": period, "match_time_ms": ms,
         "emitted_at": (BASE + timedelta(milliseconds=ms)).isoformat(timespec="milliseconds").replace("+00:00", "Z")}
    e.update(extra)
    e["payload"] = payload
    events.append(e)


def pt(x, y):
    return {"x": x, "y": y}


add("match_metadata", 0, 0, {
    "synthetic": True,
    "competition": "Synthetic Premier Division",
    "venue": "Northgate Park",
    "teams": [
        {"team_id": HOME, "name": "Northgate FC", "short_name": "NGT", "side": "home", "primary_color": "#1F4E9C"},
        {"team_id": AWAY, "name": "Aldermoor United", "short_name": "ALD", "side": "away", "primary_color": "#B22222"},
    ],
    "players": roster(),
    "generator": {"name": "contract-fixture", "version": "0.0.1", "seed": 7},
    "tracking_hz": 5,
    "pitch": {"length_m": 105, "width_m": 68},
})
add("period_start", 1, 0, {"home_attacking_towards": "+x"})
add("possession_change", 1, 0, {"cause": "kick_off", "previous_team_id": None},
    team_id=HOME, possession_id="pos_00001", location=pt(52.5, 34))
add("pass", 1, 1200, {"receiver_id": "p_109", "end_location": pt(60, 30), "outcome": "complete",
                      "height": "ground", "body_part": "foot", "set_piece": "none"},
    team_id=HOME, player_id="p_108", location=pt(52.5, 34), possession_id="pos_00001")
add("pass", 1, 3400, {"receiver_id": "p_110", "end_location": pt(72, 40), "outcome": "complete",
                      "height": "ground", "body_part": "foot", "set_piece": "none"},
    team_id=HOME, player_id="p_109", location=pt(60, 30), possession_id="pos_00001")
add("pressure", 1, 5000, {"target_player_id": "p_110", "distance_m": 2.1, "duration_ms": 1800, "forced_turnover": True},
    team_id=AWAY, player_id="p_205", location=pt(73, 41), possession_id="pos_00001")
add("tackle", 1, 6100, {"outcome": "won", "tackled_player_id": "p_110"},
    team_id=AWAY, player_id="p_205", location=pt(73, 41), possession_id="pos_00001")
add("possession_change", 1, 6100, {"cause": "tackle", "previous_team_id": HOME},
    team_id=AWAY, possession_id="pos_00002", location=pt(73, 41))
add("pass", 1, 8000, {"receiver_id": "p_207", "end_location": pt(62, 36), "outcome": "complete",
                      "height": "ground", "body_part": "foot", "set_piece": "none"},
    team_id=AWAY, player_id="p_205", location=pt(73, 41), possession_id="pos_00002")
add("tracking_frame", 1, 8000, {
    "frame_index": 0,
    "ball": {"x": 73.0, "y": 41.0, "z": 0.1, "speed_kmh": 41.2},
    "players": [{"player_id": "p_205", "x": 73.1, "y": 41.0, "speed_kmh": 12.4},
                {"player_id": "p_207", "x": 63.5, "y": 36.2, "speed_kmh": 9.8},
                {"player_id": "p_110", "x": 74.0, "y": 40.2, "speed_kmh": 6.1}]})
add("tracking_frame", 1, 8200, {
    "frame_index": 1,
    "ball": {"x": 70.4, "y": 40.1, "z": 0.1, "speed_kmh": 39.0},
    "players": [{"player_id": "p_205", "x": 72.9, "y": 40.9, "speed_kmh": 10.1},
                {"player_id": "p_207", "x": 63.2, "y": 36.3, "speed_kmh": 10.4},
                {"player_id": "p_110", "x": 74.0, "y": 40.0, "speed_kmh": 5.2}]})
add("pass", 1, 12000, {"receiver_id": "p_209", "end_location": pt(50, 28), "outcome": "intercepted",
                       "height": "low", "body_part": "foot", "set_piece": "none"},
    team_id=AWAY, player_id="p_207", location=pt(62, 36), possession_id="pos_00002")
add("possession_change", 1, 12100, {"cause": "interception", "previous_team_id": AWAY},
    team_id=HOME, possession_id="pos_00003", location=pt(50, 28))
add("pass", 1, 18000, {"receiver_id": "p_110", "end_location": pt(78, 35), "outcome": "complete",
                       "height": "low", "body_part": "foot", "set_piece": "none"},
    team_id=HOME, player_id="p_108", location=pt(50, 28), possession_id="pos_00003")
add("shot", 1, 20500, {"outcome": "goal", "body_part": "foot", "situation": "counter", "xg": 0.31,
                       "xg_model": "receipts-xg-1", "ball_speed_kmh": 96.4,
                       "target": {"y": 34.6, "z": 1.2}, "goalkeeper_id": "p_201",
                       "assist_event_id": "ev_0000014"},
    team_id=HOME, player_id="p_110", location=pt(94, 34), possession_id="pos_00003")
add("period_end", 1, 2820000, {"added_time_ms": 120000, "is_final": False})

out = Path(__file__).resolve().parent.parent / "examples" / "valid" / "match_stream.jsonl"
out.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
print(f"wrote {len(events)} events -> {out}")
