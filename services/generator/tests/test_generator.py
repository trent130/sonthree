from __future__ import annotations

import json
import math
import random
import threading
import time
from pathlib import Path

import pytest
from validate import check_event_stream, validate_event

from generator.demo import (
    canonical_jsonl,
    cut_first_minutes,
    find_demo_seed,
    score_demo,
    verify_demo,
    write_demo,
)
from generator.momentum import MomentumProcess
from generator.names import REAL_NAME_BLOCKLIST, ensure_fictional
from generator.realism import TARGETS, MetricResult, evaluate_seeds, parse_seeds, render_report
from generator.simulation import generate_match
from generator.streaming import StreamControl, stream_events
from generator.xg import MODEL_ID, expected_goals, shot_distance_and_angle
from receipts_common.bus import LocalEventBus

ROOT = Path(__file__).resolve().parents[3]


def _compact(events: list[dict]) -> bytes:
    return b"".join(
        (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for event in events
    )


def test_short_match_is_deterministic_and_validates_every_event() -> None:
    first = generate_match(seed=173, minutes=2, tracking_hz=2)
    second = generate_match(seed=173, minutes=2, tracking_hz=2)
    assert _compact(first) == _compact(second)
    assert all(not validate_event(event) for event in first[:10])
    assert not check_event_stream(first)
    metadata = first[0]["payload"]
    assert metadata["synthetic"] is True
    assert metadata["generator"]["seed"] == 173
    assert metadata["generator"]["version"]
    assert {event["type"] for event in first} >= {"period_start", "period_end", "possession_change"}


def test_generated_names_are_fictional_and_blocklist_is_enforced() -> None:
    events = generate_match(seed=19, minutes=2, tracking_hz=1)
    metadata = events[0]["payload"]
    names = [team["name"] for team in metadata["teams"]]
    names.extend(player["name"] for player in metadata["players"])
    assert not ({name.casefold() for name in names} & REAL_NAME_BLOCKLIST)
    with pytest.raises(ValueError, match="blocklist"):
        ensure_fictional(["Lionel Messi"])


def test_possession_events_have_spell_ids_and_turnover_causes_match_predecessors() -> None:
    events = generate_match(seed=42, minutes=2, tracking_hz=1)
    for event in events:
        if event["type"] in {"pass", "shot", "tackle", "pressure"}:
            assert event.get("possession_id")
    for index, event in enumerate(events):
        if event["type"] != "possession_change" or event["payload"]["cause"] == "kick_off":
            continue
        cause = event["payload"]["cause"]
        previous = events[index - 1]
        if cause == "tackle":
            assert previous["type"] == "tackle"
        elif cause == "interception":
            assert previous["type"] == "pass" and previous["payload"]["outcome"] == "intercepted"


def test_shot_model_is_bounded_and_calibrated_for_synthetic_shot_locations() -> None:
    xgs = []
    for x in range(80, 101):
        for y in range(23, 46):
            xgs.append(expected_goals(x, y, 105))
    assert MODEL_ID == "receipts-xg-1"
    assert all(0.0 < xg < 1.0 for xg in xgs)
    assert 0.08 <= sum(xgs) / len(xgs) <= 0.12


def test_shot_angle_uses_post_vectors_and_is_symmetric() -> None:
    distance, center_angle = shot_distance_and_angle(90, 34, 105)
    _, lower_angle = shot_distance_and_angle(90, 31, 105)
    _, mirrored_angle = shot_distance_and_angle(90, 37, 105)
    _, opposite_end_angle = shot_distance_and_angle(15, 34, 0)
    expected_center_angle = math.degrees(2 * math.atan(3.66 / 15))
    assert math.isclose(distance, 15.0)
    assert math.isclose(center_angle, expected_center_angle, abs_tol=1e-9)
    assert lower_angle < center_angle
    assert math.isclose(lower_angle, mirrored_angle, abs_tol=1e-9)
    assert math.isclose(center_angle, opposite_end_angle, abs_tol=1e-9)


def test_tracking_speeds_match_displacement_and_ball_is_at_event_locations() -> None:
    events = generate_match(seed=91, minutes=2, tracking_hz=1)
    frames = [event for event in events if event["type"] == "tracking_frame"]
    prior: dict[str, tuple[float, float]] = {}
    previous_time: int | None = None
    for frame in frames:
        dt = None if previous_time is None else (frame["match_time_ms"] - previous_time) / 1000
        for player in frame["payload"]["players"]:
            point = (player["x"], player["y"])
            if dt and player["player_id"] in prior:
                implied = math.dist(point, prior[player["player_id"]]) / dt * 3.6
                reported = player["speed_kmh"]
                assert abs(implied - reported) <= max(0.02, implied * 0.15)
                assert reported <= 40
            prior[player["player_id"]] = point
        previous_time = frame["match_time_ms"]
    frame_by_time = {frame["match_time_ms"]: frame for frame in frames}
    for event in events:
        if event["type"] not in {"pass", "shot"}:
            continue
        frame = frame_by_time[event["match_time_ms"]]
        ball = frame["payload"]["ball"]
        event_location = (event["location"]["x"], event["location"]["y"])
        assert math.dist((ball["x"], ball["y"]), event_location) <= 1.5


def test_fouls_cards_substitutions_and_momentum_are_seeded_and_bounded() -> None:
    events = generate_match(seed=73, minutes=20, tracking_hz=1)
    for index, event in enumerate(events):
        if event["type"] == "card":
            assert events[index - 1]["type"] == "foul"
            assert event["payload"]["reason"] == "foul"
    assert any(event["type"] == "foul" for event in events)
    assert any(event["type"] == "substitution" for event in events)
    metadata = {player["player_id"]: player for player in events[0]["payload"]["players"]}
    for event in events:
        if event["type"] == "substitution":
            assert metadata[event["payload"]["player_off_id"]]["position"] != "GK"
            assert metadata[event["payload"]["player_on_id"]]["position"] != "GK"
    process = MomentumProcess(random.Random(3))
    values = [process.update("home", 0.08) for _ in range(10_000)]
    assert all(-1 <= value <= 1 for value in values)


def test_odd_match_duration_keeps_all_requested_playing_time() -> None:
    events = generate_match(seed=31, minutes=3, tracking_hz=1)
    ends = [event for event in events if event["type"] == "period_end"]
    first_end, final_end = ends
    assert first_end["match_time_ms"] - first_end["payload"]["added_time_ms"] == 90_000
    assert (
        final_end["match_time_ms"]
        - first_end["match_time_ms"]
        - final_end["payload"]["added_time_ms"]
        == 90_000
    )


def test_realism_report_uses_all_targets_and_names_failures() -> None:
    results, matches = evaluate_seeds([1, 2, 3, 4, 5])
    assert len(results) == len(TARGETS)
    assert len(matches) == 5
    report = render_report(results, seed_count=5)
    assert "receipts-xg-1" in report
    assert "Target range sources" in report
    assert "| goals per match |" in report
    forced_failure = render_report(
        [MetricResult("goals per match", 1.0, 2.4, 3.2, False)], seed_count=5
    )
    assert "**Status:** FAIL" in forced_failure
    assert "| goals per match | 1.000 | 2.4–3.2 | FAIL |" in forced_failure


def test_seed_list_parses_ranges_and_rejects_malformed_or_out_of_range() -> None:
    assert parse_seeds("1-3, 7,3") == [1, 2, 3, 7]
    for seed_text in ("", "3-1", "-1", "4294967296", "1,,2"):
        with pytest.raises(ValueError):
            parse_seeds(seed_text)


def test_stream_seek_stamps_publishes_and_pause_resume_does_not_duplicate() -> None:
    events = generate_match(seed=82, minutes=2, tracking_hz=1, include_tracking=False)
    events = [dict(event, match_time_ms=0) for event in events]
    bus = LocalEventBus()
    control = StreamControl()
    control.pause()
    done = threading.Event()
    published: list[int] = []

    def publish() -> None:
        published.append(
            stream_events(
                events,
                bus,
                speed=60,
                from_seq=4,
                control=control,
                now=lambda: "2026-10-16T00:00:00.000Z",
            )
        )
        done.set()

    worker = threading.Thread(target=publish)
    worker.start()
    assert not done.wait(0.02)
    control.resume()
    worker.join(timeout=2)
    assert done.is_set()
    records = bus.records("events")
    assert published == [len(events) - 3]
    assert [record.doc["seq"] for record in records] == list(range(4, len(events) + 1))
    assert len({record.doc["seq"] for record in records}) == len(records)
    assert all(record.doc["emitted_at"] == "2026-10-16T00:00:00.000Z" for record in records)


def test_demo_cut_remaps_gapless_ids_and_demo_candidate_flags():
    events = generate_match(seed=29, minutes=4, tracking_hz=1, include_tracking=False)
    cut = cut_first_minutes(events, minutes=2)
    assert cut
    assert cut[-1]["match_time_ms"] <= 120_000
    assert [event["seq"] for event in cut] == list(range(1, len(cut) + 1))
    assert all(event["event_id"] == f"ev_{event['seq']:07d}" for event in cut)
    assert len(canonical_jsonl(cut)) > 0
    candidate = score_demo(events, seed=29)
    assert candidate.score == sum(
        (candidate.first_half_goal, candidate.lead_change,
         candidate.forced_turnover_to_shot, candidate.card)
    )


def test_demo_search_selects_richest_complete_candidate():
    candidate, events = find_demo_seed(range(1, 100))
    assert candidate.complete
    assert score_demo(cut_first_minutes(events), candidate.seed).complete
    assert events[0]["payload"]["generator"]["seed"] == candidate.seed


def test_demo_artifact_verification_checks_independent_pinned_files(tmp_path):
    config = tmp_path / "config/demo.json"
    cut = tmp_path / "tests/golden/demo-20min.jsonl"
    golden = tmp_path / "tests/golden/demo-20min.sha256"
    write_demo([82], config, cut, golden)
    passed, digest = verify_demo(config, cut, golden)
    assert passed
    assert digest == json.loads(config.read_text())["cut_sha256"]

    config_doc = json.loads(config.read_text())
    config_doc["cut_narrative_flags"]["card"] = not config_doc["cut_narrative_flags"]["card"]
    config.write_text(json.dumps(config_doc))
    passed, message = verify_demo(config, cut, golden)
    assert not passed
    assert "cut narrative flags" in message


def test_stream_pacing_at_sixty_times_uses_scaled_match_clock_delays():
    events = generate_match(seed=16, minutes=2, tracking_hz=1, include_tracking=False)
    bus = LocalEventBus()
    delays: list[float] = []
    count = stream_events(events[:12], bus, speed=60, sleep=delays.append)
    assert count == 12
    assert len(delays) == count - 1
    assert all(delay >= 0 for delay in delays)
    for previous, event, delay in zip(events[:11], events[1:12], delays, strict=True):
        expected = max(0, event["match_time_ms"] - previous["match_time_ms"]) / 60_000
        assert math.isclose(delay, expected, abs_tol=1e-9)


def test_full_match_tracking_generation_stays_under_sixty_seconds():
    started = time.perf_counter()
    events = generate_match(seed=615, minutes=90, tracking_hz=5)
    elapsed = time.perf_counter() - started
    assert elapsed < 60
    assert sum(event["type"] == "tracking_frame" for event in events) >= 27_000
    assert not check_event_stream(events)


def test_contract_example_fixture_still_validates_without_being_copied() -> None:
    fixture = ROOT / "contracts/examples/valid/match_stream.jsonl"
    events = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    assert not any(validate_event(event) for event in events)
    assert not check_event_stream(events)