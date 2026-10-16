# Spec 02: Stats engine (Interpret, deterministic half)

A thin service around `contracts/stats_ref.py`. It produces snapshots and match state. It must not reimplement any formula.

## User stories
- As the Analyst and overlay compiler, I want trustworthy numbers by id, so I never compute statistics myself.
- As the Verifier, I want the exact same numbers recomputed on demand, so a claim can be checked.

## Requirements

### 1. Snapshots
1.1 WHEN the engine receives an event that is not a `tracking_frame` THEN it SHALL be eligible to produce snapshots as of that `seq`.
1.2 WHEN a snapshot is requested with a window, subjects and metrics THEN the engine SHALL return a snapshot document whose values come only from `stats_ref` and which passes `validate_snapshot` and `check_snapshots`.
1.3 THE engine SHALL omit metrics that `stats_ref` reports as undefined, and SHALL reject requests whose metric is outside the metric's allowed subject types.
1.4 THE engine SHALL allocate `snap_` ids monotonically per match and return the same snapshot id for an identical request (same match, `as_of_seq`, window, subject and metric set).
1.5 THE engine SHALL record `stats_engine_version` from `stats_ref` in every snapshot and refuse to start if its version differs from the installed contracts.

### 2. Standing snapshots
2.1 THE engine SHALL maintain a rolling team snapshot (control, pressure and rhythm index, possession, xG, shots) for the last 5 minutes and for the whole match, refreshed at every non-frame event and at least every 30 seconds of match time.
2.2 WHEN a player crosses a configured speed or distance threshold in a tracking frame THEN the engine SHALL create a snapshot containing that player's `top_speed_kmh` or `distance_km` and publish a `threshold` notice carrying the snapshot id.
2.3 THE thresholds SHALL be configuration, with defaults of 30 km/h speed and 5 km distance, and SHALL never fire twice for the same player and threshold within 60 seconds of match time.

### 3. Match state
3.1 WHEN the engine builds a match state THEN it SHALL derive `status`, `score`, the whole-match `snapshot_id` and the `key_moments` list exactly as `validate.check_match_state` requires.
3.2 THE engine SHALL refresh match state at every period boundary and on request, and SHALL publish it on the `matchstate` topic.

### 4. Verifier support
4.1 THE engine SHALL expose `recompute(subject, metric, window, as_of_seq)` returning the value and `stats_engine_version`, used by the Verifier, with no caching that could return a stale value for a different `as_of_seq`.

### 5. Performance
5.1 WHEN the stream is a full 90-minute match THEN a snapshot request SHALL complete in under 100 ms at the 95th percentile.
5.2 IF the target in 5.1 is not met by wrapping `stats_ref` THEN an incremental implementation MAY be added, and it SHALL pass the differential test in 6.1 on at least 1,000 random requests.

### 6. Correctness
6.1 THE engine SHALL be tested against `stats_ref` directly on random subjects, metrics, windows and `as_of_seq` values, with zero tolerated differences beyond rounding.
6.2 THE engine SHALL pass `validate.py` with `--snapshots` on all output of the demo match.
