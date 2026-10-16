"""Reference stats engine (definitions v0.1.0). See STATS.md for the prose version.

Pure Python, no I/O, deterministic. The production stats engine and the Verifier both import this
module; the validator uses it to recompute every snapshot value. Changing any formula or constant
here means bumping STATS_ENGINE_VERSION, because published numbers depend on it.

A subject is {"entity_type": "player" | "team" | "match", "entity_id": str}.
A window is {"from_ms": int, "to_ms": int}, inclusive, on the continuous match clock.
metric() returns None when a metric is undefined for that subject and window (for example pass
accuracy with no passes), and snapshots simply omit it.
"""
from __future__ import annotations

import bisect
import math

STATS_ENGINE_VERSION = "0.1.0"

PITCH_LENGTH_M = 105.0
STABLE_SPELL_MS = 8000            # a possession spell this long counts as "stable"
CONTROL_WEIGHTS = (0.6, 0.4)      # (possession share, stability)
PRESSURE_BASELINE_PER_MIN = 6.0   # defensive actions per minute that score 100
RHYTHM_BASELINE_PER_MIN = 30.0    # on-ball events per minute that score 100
PPDA_ZONE_MIN_M = 42.0            # distance from the passer's own goal line where pressing "counts"
SPRINT_KMH = 25.0
SPRINT_MIN_MS = 1000
FRAME_GAP_FACTOR = 1.5            # consecutive frames further apart than this x frame interval are not linked
PRESSURE_FRAME_MAX_AGE_MS = 1000  # tracking frame must be this fresh to measure defender distance
HEIGHT_TERM = {"ground": 0.0, "low": 0.5, "high": 1.0}
DIFFICULTY_WEIGHTS = {"length": 0.4, "height": 0.2, "progress": 0.2, "pressure": 0.2}
ROUND_DP = 4


def _r(x: float) -> float:
    return round(float(x), ROUND_DP)


class StatsContext:
    """Everything needed to compute metrics from events with seq <= as_of_seq."""

    def __init__(self, events: list[dict], as_of_seq: int):
        self.events = events[:as_of_seq]
        meta = self.events[0]["payload"]
        self.teams = [t["team_id"] for t in meta["teams"]]
        self.home = next(t["team_id"] for t in meta["teams"] if t["side"] == "home")
        self.roster = {p["player_id"]: p["team_id"] for p in meta["players"]}
        self.hz = meta["tracking_hz"]
        self.home_sign: dict[int, int] = {}
        for e in self.events:
            if e["type"] == "period_start":
                self.home_sign[e["period"]] = 1 if e["payload"]["home_attacking_towards"] == "+x" else -1
        self.frames = [e for e in self.events if e["type"] == "tracking_frame"]
        self.frame_times = [f["match_time_ms"] for f in self.frames]
        self._spans = self._build_spans()

    # ------------------------------------------------------------ helpers
    def attack_dir(self, team_id: str, period: int) -> int:
        s = self.home_sign.get(period, 1)
        return s if team_id == self.home else -s

    def opponent(self, team_id: str) -> str:
        return next(t for t in self.teams if t != team_id)

    def members(self, subj: dict) -> set[str]:
        t, i = subj["entity_type"], subj["entity_id"]
        if t == "player":
            return {i}
        if t == "team":
            return {p for p, tm in self.roster.items() if tm == i}
        return set(self.roster)

    def _mine(self, e: dict, subj: dict) -> bool:
        t, i = subj["entity_type"], subj["entity_id"]
        if t == "player":
            return e.get("player_id") == i
        if t == "team":
            return e.get("team_id") == i
        return True

    def _evs(self, types, w: dict, subj: dict | None = None) -> list[dict]:
        return [e for e in self.events
                if e["type"] in types and w["from_ms"] <= e["match_time_ms"] <= w["to_ms"]
                and (subj is None or self._mine(e, subj))]

    def _frames_in(self, w: dict) -> list[dict]:
        return [f for f in self.frames if w["from_ms"] <= f["match_time_ms"] <= w["to_ms"]]

    def _frame_before(self, t_ms: int, max_age_ms: int):
        i = bisect.bisect_right(self.frame_times, t_ms) - 1
        if i >= 0 and t_ms - self.frame_times[i] <= max_age_ms:
            return self.frames[i]
        return None

    # ------------------------------------------------------------ possession
    def _build_spans(self):
        spans, cur = [], None
        for e in self.events:
            if e["type"] == "possession_change":
                if cur:
                    spans.append((cur[0], cur[1], e["match_time_ms"]))
                cur = (e["team_id"], e["match_time_ms"])
            elif e["type"] == "period_end":
                if cur:
                    spans.append((cur[0], cur[1], e["match_time_ms"]))
                cur = None
        if cur:
            spans.append((cur[0], cur[1], None))   # open span: runs to the end of the window
        return spans

    def _clipped_spans(self, w: dict) -> list[tuple[str, int]]:
        out = []
        for team, start, end in self._spans:
            end = w["to_ms"] if end is None else min(end, w["to_ms"])
            start = max(start, w["from_ms"])
            if end > start:
                out.append((team, end - start))
        return out

    def _possession_share(self, team: str, w: dict):
        spans = self._clipped_spans(w)
        total = sum(d for _, d in spans)
        if total == 0:
            return None
        return sum(d for t, d in spans if t == team) / total

    def _stability(self, team: str, w: dict) -> float:
        mine = [d for t, d in self._clipped_spans(w) if t == team]
        return (sum(1 for d in mine if d >= STABLE_SPELL_MS) / len(mine)) if mine else 0.0

    # ------------------------------------------------------------ pass difficulty
    def pass_difficulty(self, e: dict) -> float:
        s, t = e["location"], e["payload"]["end_location"]
        length = math.hypot(t["x"] - s["x"], t["y"] - s["y"])
        forward = (t["x"] - s["x"]) * self.attack_dir(e["team_id"], e["period"])
        progress = min(max(forward / 30.0, 0.0), 1.0)
        pressure = 0.0
        f = self._frame_before(e["match_time_ms"], PRESSURE_FRAME_MAX_AGE_MS)
        if f:
            opp = [p for p in f["payload"]["players"] if self.roster[p["player_id"]] != e["team_id"]]
            if opp:
                d = min(math.hypot(p["x"] - s["x"], p["y"] - s["y"]) for p in opp)
                pressure = 1.0 - min(d / 10.0, 1.0)
        wts = DIFFICULTY_WEIGHTS
        return (wts["length"] * min(length / 40.0, 1.0) + wts["height"] * HEIGHT_TERM[e["payload"]["height"]]
                + wts["progress"] * progress + wts["pressure"] * pressure)

    # ------------------------------------------------------------ the metric registry
    def metric(self, subj: dict, metric: str, w: dict):
        fn = getattr(self, "_m_" + metric, None)
        if fn is None:
            raise KeyError(f"unknown metric {metric}")
        v = fn(subj, w)
        return None if v is None else _r(v)

    def _m_goals(self, s, w):
        return sum(1 for e in self._evs({"shot"}, w, s) if e["payload"]["outcome"] == "goal")

    def _m_shots(self, s, w):
        return len(self._evs({"shot"}, w, s))

    def _m_shots_on_target(self, s, w):
        return sum(1 for e in self._evs({"shot"}, w, s) if e["payload"]["outcome"] in ("goal", "saved"))

    def _m_xg(self, s, w):
        return sum(e["payload"]["xg"] for e in self._evs({"shot"}, w, s))

    def _m_passes(self, s, w):
        return len(self._evs({"pass"}, w, s))

    def _m_pass_accuracy_pct(self, s, w):
        ps = self._evs({"pass"}, w, s)
        return 100.0 * sum(1 for e in ps if e["payload"]["outcome"] == "complete") / len(ps) if ps else None

    def _m_avg_pass_length_m(self, s, w):
        ps = self._evs({"pass"}, w, s)
        if not ps:
            return None
        return sum(math.hypot(e["payload"]["end_location"]["x"] - e["location"]["x"],
                              e["payload"]["end_location"]["y"] - e["location"]["y"]) for e in ps) / len(ps)

    def _m_avg_pass_difficulty(self, s, w):
        ps = self._evs({"pass"}, w, s)
        return sum(self.pass_difficulty(e) for e in ps) / len(ps) if ps else None

    def _m_tackles_won(self, s, w):
        return sum(1 for e in self._evs({"tackle"}, w, s) if e["payload"]["outcome"] == "won")

    def _m_pressures(self, s, w):
        return len(self._evs({"pressure"}, w, s))

    def _m_possession_pct(self, s, w):
        share = self._possession_share(s["entity_id"], w)
        return None if share is None else 100.0 * share

    def _m_control_index(self, s, w):
        share = self._possession_share(s["entity_id"], w)
        if share is None:
            return None
        a, b = CONTROL_WEIGHTS
        return 100.0 * (a * share + b * self._stability(s["entity_id"], w))

    @staticmethod
    def _minutes(w):
        return (w["to_ms"] - w["from_ms"]) / 60000.0

    def _m_pressure_index(self, s, w):
        if w["to_ms"] <= w["from_ms"]:
            return None
        n = len(self._evs({"tackle", "pressure", "foul"}, w, s))
        return min(100.0, 100.0 * (n / self._minutes(w)) / PRESSURE_BASELINE_PER_MIN)

    def _m_rhythm_index(self, s, w):
        if w["to_ms"] <= w["from_ms"]:
            return None
        n = len(self._evs({"pass", "shot", "tackle", "foul"}, w, s))
        return min(100.0, 100.0 * (n / self._minutes(w)) / RHYTHM_BASELINE_PER_MIN)

    def _in_zone(self, e: dict, defender_team: str) -> bool:
        """Is e.location at least PPDA_ZONE_MIN_M from the defender team's own goal line?"""
        goal_x = 0.0 if self.attack_dir(defender_team, e["period"]) > 0 else PITCH_LENGTH_M
        return abs(e["location"]["x"] - goal_x) >= PPDA_ZONE_MIN_M

    def _m_ppda(self, s, w):
        me, opp = s["entity_id"], self.opponent(s["entity_id"])
        opp_subj = {"entity_type": "team", "entity_id": opp}
        passes = [e for e in self._evs({"pass"}, w, opp_subj) if self._in_zone(e, opp)]
        actions = [e for e in self._evs({"tackle", "pressure", "foul"}, w, s) if self._in_zone(e, opp)]
        return len(passes) / len(actions) if actions else None

    def _step_ok(self, t0: int, t1: int) -> bool:
        return t1 - t0 <= FRAME_GAP_FACTOR * 1000.0 / self.hz

    def _player_track(self, pid: str, frames: list[dict]):
        for f in frames:
            for p in f["payload"]["players"]:
                if p["player_id"] == pid:
                    yield f["match_time_ms"], p
                    break

    def _m_distance_km(self, s, w):
        frames = self._frames_in(w)
        total, any_step = 0.0, False
        for pid in self.members(s):
            last = None
            for t, p in self._player_track(pid, frames):
                if last and self._step_ok(last[0], t):
                    total += math.hypot(p["x"] - last[1], p["y"] - last[2])
                    any_step = True
                last = (t, p["x"], p["y"])
        return total / 1000.0 if any_step else None

    def _m_top_speed_kmh(self, s, w):
        speeds = [p["speed_kmh"] for pid in self.members(s) for _, p in self._player_track(pid, self._frames_in(w))]
        return max(speeds) if speeds else None

    def _m_sprints(self, s, w):
        frames = self._frames_in(w)
        if not frames:
            return None
        runs = 0
        for pid in self.members(s):
            start = last = None
            for t, p in self._player_track(pid, frames):
                fast = p["speed_kmh"] >= SPRINT_KMH
                if fast and last is not None and self._step_ok(last, t):
                    last = t
                    continue
                if start is not None and last - start >= SPRINT_MIN_MS:
                    runs += 1
                start = last = t if fast else None
            if start is not None and last - start >= SPRINT_MIN_MS:
                runs += 1
        return runs

    def _m_max_ball_speed_kmh(self, s, w):
        speeds = [f["payload"]["ball"]["speed_kmh"] for f in self._frames_in(w)]
        speeds += [e["payload"]["ball_speed_kmh"] for e in self._evs({"shot"}, w)]
        return max(speeds) if speeds else None

    def _m_max_shot_speed_kmh(self, s, w):
        speeds = [e["payload"]["ball_speed_kmh"] for e in self._evs({"shot"}, w, s)]
        return max(speeds) if speeds else None
