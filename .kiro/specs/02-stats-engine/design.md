# Design: Stats engine

## Shape
A Python package `services/stats` with a pure library and a thin runner:

```
stats/
  service.py      StatsService: snapshot(), recompute(), match_state()
  standing.py     rolling and whole-match snapshot scheduler, threshold detector
  cache.py        snapshot dedupe keyed by (match_id, as_of_seq, window, subjects, metrics)
  runner.py       subscribes to `events`, publishes `snapshots`, `matchstate`, notices
  cli.py          python -m stats snapshot|state|replay
```

## Key decisions
- **Wrap, do not port.** `StatsService.snapshot` builds a `StatsContext(events, as_of_seq)` and calls `metric()`. The first version is deliberately naive so it is correct by construction.
- **Context reuse.** Building a `StatsContext` is O(events). The service keeps one context per `as_of_seq` in a small LRU and builds snapshots at trigger events only, never per tracking frame, so cumulative work stays bounded.
- **Only if needed, go incremental.** If benchmarks miss 5.1, add accumulators (running goals, xG, possession spans, frame distance and speed) behind the same interface. The differential test (6.1) is the gate. Do not start there.
- **Dedupe cache** key includes the full request, so identical requests return the same `snap_` id and no duplicate documents reach the audit log.
- **Match state builder** calls `validate.eligible_claims` against the Store for key moments, so state and validator cannot disagree.
- **Threshold detector** reads tracking frames as they arrive, keeps per-player cooldowns on match time, and asks the service for a minimal snapshot (one player, one metric) so the overlay can cite it.
- **Window choice for snapshots:** `to_ms` is always the match time of the `as_of_seq` event, which satisfies the "closed window" rule by construction.

## Interfaces
```
snapshot(match_id, as_of_seq, window, requests: list[{subject, metrics}]) -> Snapshot
recompute(subject, metric, window, as_of_seq) -> {value|None, stats_engine_version}
match_state(match_id, as_of_seq) -> MatchState
```

## Testing
Differential test against `stats_ref` (Hypothesis-style random requests over generator output). Contract tests: output of every call passes `validate_snapshot`, `check_snapshots`, `check_match_state`. Benchmark test records p95 on a 90-minute demo match and fails above the target. Threshold tests for firing, cooldown and no double firing.
