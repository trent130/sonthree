"""Batch realism evaluation for seeded synthetic matches."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import GENERATOR_VERSION
from .simulation import MatchGenerator

TARGETS = {
    "goals per match": (2.4, 3.2),
    "shots per team per match": (9.0, 15.0),
    "mean xG per shot": (0.08, 0.12),
    "pass completion percent": (78.0, 88.0),
    "passes per team per match": (350.0, 600.0),
    "possession share coverage": (90.0, 100.0),
    "fouls per team per match": (8.0, 14.0),
    "yellow cards per match": (2.0, 5.0),
    "red cards per match": (0.0, 0.15),
    "top player speed km/h": (30.0, 36.0),
}


@dataclass(frozen=True)
class MetricResult:
    name: str
    value: float
    lower: float
    upper: float
    passed: bool


def parse_seeds(value: str) -> list[int]:
    """Parse a comma-separated seed list and inclusive ranges such as 1-200."""
    seeds: set[int] = set()
    try:
        for part in value.split(","):
            part = part.strip()
            if not part:
                raise ValueError
            if "-" in part:
                first, last = (int(piece) for piece in part.split("-", 1))
                if last < first:
                    raise ValueError
                seeds.update(range(first, last + 1))
            else:
                seeds.add(int(part))
    except ValueError as exc:
        raise ValueError(f"invalid seed list: {value!r}") from exc
    if not seeds or min(seeds) < 0 or max(seeds) > 4_294_967_295:
        raise ValueError("seed list must contain values from 0 to 4294967295")
    return sorted(seeds)


def _match_metrics(events: list[dict], top_speed_kmh: float) -> dict[str, float]:
    metadata = events[0]["payload"]
    teams = [team["team_id"] for team in metadata["teams"]]
    passes = defaultdict(int)
    completed = defaultdict(int)
    shots = defaultdict(int)
    fouls = defaultdict(int)
    goals = 0
    xg_sum = 0.0
    xg_count = 0
    yellows = 0
    reds = 0
    possession_ms = defaultdict(int)
    current_team: str | None = None
    current_time: int | None = None

    for event in events:
        event_type = event["type"]
        team_id = event.get("team_id")
        payload = event["payload"]
        if event_type == "pass":
            passes[team_id] += 1
            completed[team_id] += payload["outcome"] == "complete"
        elif event_type == "shot":
            shots[team_id] += 1
            xg_sum += payload["xg"]
            xg_count += 1
            goals += payload["outcome"] == "goal"
        elif event_type == "foul":
            fouls[team_id] += 1
        elif event_type == "card":
            yellows += payload["card"] == "yellow"
            reds += payload["card"] == "red"
        elif event_type == "possession_change":
            now = event["match_time_ms"]
            if current_team is not None and current_time is not None:
                possession_ms[current_team] += max(0, now - current_time)
            current_team, current_time = team_id, now
        elif event_type == "period_end" and current_team is not None and current_time is not None:
            now = event["match_time_ms"]
            possession_ms[current_team] += max(0, now - current_time)
            current_team, current_time = None, None

    total_possession = sum(possession_ms.values())
    values = {
        "goals": float(goals),
        "shots_per_team": sum(shots.values()) / len(teams),
        "xg_per_shot": xg_sum / xg_count if xg_count else 0.0,
        "pass_completion_pct": 100.0 * sum(completed.values()) / sum(passes.values())
        if sum(passes.values())
        else 0.0,
        "passes_per_team": sum(passes.values()) / len(teams),
        "possession_in_range": float(
            sum(
                35.0 <= 100.0 * possession_ms[team] / total_possession <= 65.0
                for team in teams
            )
        )
        / len(teams)
        if total_possession
        else 0.0,
        "fouls_per_team": sum(fouls.values()) / len(teams),
        "yellows": float(yellows),
        "reds": float(reds),
        "top_speed_kmh": top_speed_kmh,
    }
    return values


def evaluate_seeds(seeds: list[int]) -> tuple[list[MetricResult], list[dict[str, float]]]:
    """Generate 90-minute, tracking-free analysis streams and calculate batch metrics."""
    matches: list[dict[str, float]] = []
    for seed in seeds:
        generator = MatchGenerator(seed, minutes=90, tracking_hz=1)
        events = generator.generate(include_tracking=False)
        matches.append(_match_metrics(events, generator.top_speed_kmh))

    possession_coverage = 100.0 * sum(
        match["possession_in_range"] == 1.0 for match in matches
    ) / len(matches)
    averages = {
        "goals per match": sum(match["goals"] for match in matches) / len(matches),
        "shots per team per match": sum(
            match["shots_per_team"] for match in matches
        ) / len(matches),
        "mean xG per shot": sum(match["xg_per_shot"] for match in matches) / len(matches),
        "pass completion percent": sum(
            match["pass_completion_pct"] for match in matches
        ) / len(matches),
        "passes per team per match": sum(
            match["passes_per_team"] for match in matches
        ) / len(matches),
        "possession share coverage": possession_coverage,
        "fouls per team per match": sum(
            match["fouls_per_team"] for match in matches
        ) / len(matches),
        "yellow cards per match": sum(match["yellows"] for match in matches) / len(matches),
        "red cards per match": sum(match["reds"] for match in matches) / len(matches),
        "top player speed km/h": sum(match["top_speed_kmh"] for match in matches) / len(matches),
    }
    results = [
        MetricResult(name, value, lower, upper, lower <= value <= upper)
        for name, (lower, upper) in TARGETS.items()
        for value in [averages[name]]
    ]
    return results, matches


def render_report(results: list[MetricResult], seed_count: int) -> str:
    status = "PASS" if all(result.passed for result in results) else "FAIL"
    lines = [
        "# Synthetic generator data validation",
        "",
        f"**Status:** {status}  ",
        f"**Generator:** `{GENERATOR_VERSION}`  ",
        "**Evaluation:** "
        f"{seed_count} deterministic 90-minute seeds; event-only analysis at 1 Hz "
        "(tracking omitted from report workload).",
        "",
        "The evaluator uses seeded fictional teams and players only. It computes distributions "
        "from generated events; no real match or player data is bundled or replayed.",
        "",
        "| Metric | Batch mean / coverage | Target | Result |",
        "|---|---:|---:|:---:|",
    ]
    for result in results:
        display = f"{result.value:.3f}"
        suffix = "%" if "percent" in result.name or "coverage" in result.name else ""
        lines.append(
            f"| {result.name} | {display}{suffix} | "
            f"{result.lower:g}–{result.upper:g}{suffix} | "
            f"{'PASS' if result.passed else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Target range sources",
            "",
            "These are broad synthetic acceptance bands, not a fitted or reproduced league "
            "dataset. They are informed by published aggregate summaries and public competition "
            "statistics; the generator does not ingest those data.",
            "",
            "- UEFA, Champions League technical reports and competition statistics: https://www.uefa.com/uefachampionsleague/news/",
            "- Premier League, official competition statistics: https://www.premierleague.com/stats",
            "- StatsBomb, public football analytics research and xG methodology: https://statsbomb.com/articles/",
            "",
            "The xG model is a compact synthetic baseline (`receipts-xg-1`), calibrated against "
            "the fictional shot-location distribution. Targets are heuristics from the generator "
            "design and are not claims about a particular season.",
            "",
            "## Reproduction",
            "",
            "Run `python -m generator report --seeds 1-200 --out docs/data-validation.md`. "
            "The command exits non-zero and names every out-of-range metric.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(seeds: list[int], output: Path) -> tuple[bool, str]:
    results, _ = evaluate_seeds(seeds)
    report = render_report(results, len(seeds))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8", newline="\n")
    failed = [result.name for result in results if not result.passed]
    return not failed, ", ".join(failed)
