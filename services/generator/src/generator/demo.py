"""Deterministic narrative-rich seed selection and 20-minute demo cut."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from . import GENERATOR_NAME, GENERATOR_VERSION
from .simulation import MatchGenerator

CUT_MINUTES = 20


@dataclass(frozen=True)
class DemoCandidate:
    seed: int
    first_half_goal: bool
    lead_change: bool
    forced_turnover_to_shot: bool
    card: bool
    score: int

    @property
    def complete(self) -> bool:
        return (
            self.first_half_goal
            and self.lead_change
            and self.forced_turnover_to_shot
            and self.card
        )


def score_demo(events: list[dict], seed: int) -> DemoCandidate:
    first_half_goal = False
    team_ids = [team["team_id"] for team in events[0]["payload"]["teams"]]
    goals = dict.fromkeys(team_ids, 0)
    lead_change = False
    previous_leader: str | None = None
    for event in events:
        if event["type"] != "shot" or event["payload"]["outcome"] != "goal":
            continue
        team = event["team_id"]
        goals[team] += 1
        if event["period"] == 1:
            first_half_goal = True
        new_leader = (
            max(goals, key=goals.get)
            if goals[team_ids[0]] != goals[team_ids[1]]
            else None
        )
        if new_leader is not None and previous_leader is not None and new_leader != previous_leader:
            lead_change = True
        if new_leader is not None:
            previous_leader = new_leader

    forced_turnover_to_shot = False
    pressured_possession: str | None = None
    pressing_team: str | None = None
    turnover_possession: str | None = None
    for event in events:
        if event["type"] == "pressure" and event["payload"]["forced_turnover"]:
            pressured_possession = event.get("possession_id")
            pressing_team = event["team_id"]
        elif (
            event["type"] == "pass"
            and event["payload"]["outcome"] == "intercepted"
            and event.get("possession_id") == pressured_possession
        ):
            turnover_possession = None
        elif event["type"] == "possession_change":
            if (
                event["payload"]["cause"] == "interception"
                and event["team_id"] == pressing_team
                and event["payload"]["previous_team_id"]
            ):
                turnover_possession = event.get("possession_id")
            elif (
                turnover_possession is not None
                and event.get("possession_id") != turnover_possession
            ):
                turnover_possession = None
        elif event["type"] == "shot" and turnover_possession is not None:
            if (
                event["team_id"] == pressing_team
                and event.get("possession_id") == turnover_possession
            ):
                forced_turnover_to_shot = True
            turnover_possession = None

    card = any(event["type"] == "card" for event in events)
    flags = (first_half_goal, lead_change, forced_turnover_to_shot, card)
    return DemoCandidate(seed, *flags, sum(flags))


def canonical_jsonl(events: list[dict]) -> bytes:
    return b"".join(
        (json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        for event in events
    )


def cut_first_minutes(events: list[dict], minutes: int = CUT_MINUTES) -> list[dict]:
    """Return the first N match-clock minutes with a gapless sequence and remapped assists."""
    cutoff = minutes * 60_000
    cut = [event for event in events if event["match_time_ms"] <= cutoff]
    old_to_new = {event["event_id"]: f"ev_{index:07d}" for index, event in enumerate(cut, 1)}
    result = []
    for index, original in enumerate(cut, 1):
        event = json.loads(json.dumps(original))
        event["seq"] = index
        event["event_id"] = old_to_new[original["event_id"]]
        if event["type"] == "shot" and event["payload"]["assist_event_id"] is not None:
            event["payload"]["assist_event_id"] = old_to_new.get(
                event["payload"]["assist_event_id"]
            )
        result.append(event)
    return result


def find_demo_seed(seeds: list[int]) -> tuple[DemoCandidate, list[dict]]:
    """Score all candidate seeds and select the richest match; ties favor lower seed."""
    best: DemoCandidate | None = None
    best_events: list[dict] | None = None
    for seed in seeds:
        generator = MatchGenerator(seed, minutes=90, tracking_hz=1)
        events = generator.generate(include_tracking=False)
        candidate = score_demo(events, seed)
        cut_candidate = score_demo(cut_first_minutes(events, CUT_MINUTES), seed)
        combined_score = candidate.score + cut_candidate.score
        best_score = -1
        if best is not None and best_events is not None:
            best_cut = score_demo(cut_first_minutes(best_events, CUT_MINUTES), best.seed)
            best_score = best.score + best_cut.score
        if best is None or (combined_score, -candidate.seed) > (best_score, -best.seed):
            best, best_events = candidate, events
        if candidate.complete and cut_candidate.complete:
            return candidate, events
    if best is None or best_events is None:
        raise ValueError("at least one candidate seed is required")
    best_cut = score_demo(cut_first_minutes(best_events, CUT_MINUTES), best.seed)
    if not best.complete or not best_cut.complete:
        raise ValueError(
            "no candidate seed satisfies all full-match and 20-minute cut requirements; searched: "
            + ", ".join(str(seed) for seed in seeds)
        )
    return best, best_events


def write_demo(
    seeds: list[int], config_path: Path, cut_path: Path, golden_path: Path
) -> DemoCandidate:
    candidate, _ = find_demo_seed(seeds)
    match = MatchGenerator(candidate.seed, minutes=90, tracking_hz=1).generate()
    cut = cut_first_minutes(match)
    cut_candidate = score_demo(cut, candidate.seed)
    digest = hashlib.sha256(canonical_jsonl(cut)).hexdigest()
    config = {
        "generator": GENERATOR_NAME,
        "version": GENERATOR_VERSION,
        "seed": candidate.seed,
        "full_match_minutes": 90,
        "cut_minutes": CUT_MINUTES,
        "narrative_score": candidate.score,
        "narrative_flags": {
            "first_half_goal": candidate.first_half_goal,
            "lead_change": candidate.lead_change,
            "forced_turnover_to_shot": candidate.forced_turnover_to_shot,
            "card": candidate.card,
        },
        "cut_narrative_flags": {
            "first_half_goal": cut_candidate.first_half_goal,
            "lead_change": cut_candidate.lead_change,
            "forced_turnover_to_shot": cut_candidate.forced_turnover_to_shot,
            "card": cut_candidate.card,
        },
        "cut_sha256": digest,
    }
    for path, content in (
        (config_path, json.dumps(config, indent=2, sort_keys=True) + "\n"),
        (cut_path, canonical_jsonl(cut).decode("utf-8")),
        (golden_path, f"{digest}  demo-20min.jsonl\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return candidate


def verify_demo(
    config_path: Path, cut_path: Path, golden_path: Path
) -> tuple[bool, str]:
    """Check the pinned demo and committed cut against regenerated canonical bytes."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("generator") != GENERATOR_NAME or config.get("version") != GENERATOR_VERSION:
        return False, "demo config generator name/version does not match"
    if config.get("full_match_minutes") != 90 or config.get("cut_minutes") != CUT_MINUTES:
        return False, "demo config must pin a 90-minute match and 20-minute cut"

    match = MatchGenerator(int(config["seed"]), minutes=90, tracking_hz=1).generate()
    candidate = score_demo(match, int(config["seed"]))
    cut = cut_first_minutes(match, CUT_MINUTES)
    cut_candidate = score_demo(cut, int(config["seed"]))
    expected_flags = {
        "first_half_goal": candidate.first_half_goal,
        "lead_change": candidate.lead_change,
        "forced_turnover_to_shot": candidate.forced_turnover_to_shot,
        "card": candidate.card,
    }
    cut_flags = {
        "first_half_goal": cut_candidate.first_half_goal,
        "lead_change": cut_candidate.lead_change,
        "forced_turnover_to_shot": cut_candidate.forced_turnover_to_shot,
        "card": cut_candidate.card,
    }
    if not candidate.complete:
        return False, "pinned full match does not meet all narrative criteria"
    if not cut_candidate.complete:
        return False, "pinned 20-minute cut does not meet all narrative criteria"
    if config.get("narrative_flags") != expected_flags:
        return False, "full-match narrative flags differ from the generated match"
    if config.get("cut_narrative_flags") != cut_flags:
        return False, "cut narrative flags differ from the generated 20-minute cut"

    actual_bytes = canonical_jsonl(cut)
    if cut_path.read_bytes() != actual_bytes:
        return False, "committed 20-minute cut differs from generated canonical JSONL"
    actual_digest = hashlib.sha256(actual_bytes).hexdigest()
    if config.get("cut_sha256") != actual_digest:
        return False, "demo config cut_sha256 differs from generated cut"
    golden_digest = golden_path.read_text(encoding="utf-8").split()[0]
    if golden_digest != actual_digest:
        return False, "committed golden hash differs from generated cut"
    if int(config.get("narrative_score", -1)) != candidate.score:
        return False, "demo config narrative score differs from generated match"
    return True, actual_digest


def load_demo_seed(path: Path) -> int:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config["version"] != GENERATOR_VERSION:
        raise ValueError("demo config generator version does not match")
    return int(config["seed"])
