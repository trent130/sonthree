# Design: Overlay compiler

## Components
```
overlay/
  triggers.py     claim/snapshot/notice -> OverlayCandidate
  priority.py     salience, base priorities, profile boosts
  resolver.py     slot table, preemption and drop decisions (pure function of candidates and time)
  compile.py      candidate -> overlay document, latency stamping
  runner.py       subscribe, per-profile streams, publish and store
  cli.py          python -m overlay compile --events E --claims C --verdicts V --snapshots S --profiles P --out O
```

## Resolver
A pure function `resolve(candidates sorted by (trigger_seq, id), config) -> decisions`. Maintains, per kind, the list of shown overlays with `[start, end)` intervals. For each candidate in order:
1. Drop `unverified` if ineligible; drop `stale` if its earliest start is beyond the wait limit.
2. Compute earliest start = max(trigger event time + compile delay, now).
3. If a slot is free at that start, schedule.
4. Else find the lowest-priority occupant that has started; if candidate priority is greater than or equal, mark it `preempted` with `displaced_by`, truncating its end, and schedule the candidate; otherwise drop `collision`.
Being a pure function, it is property-tested against `check_overlays`: for random candidate sets the output always validates.

## Priority and personalization
`priority = min(100, round(100 × max salience) + boosts)`. Boost sources are computed from the claim's assertion subject and metric against the profile. Only the final number is validated by the contracts.

## Languages
A profile's `lang` selects the rendering. If the claim has no verified rendering in that language the lower third is simply not produced (never falls back to English silently). `--require-reviewed` is a deployment setting: in demo mode, non-English overlays need `human_reviewed` true.

## Latency
The compiler reads the trigger event's `emitted_at` from the Store, wraps the stages in spans, and writes `compiled_at` when the document is built. Aggregates are kept in a small histogram per kind and tier (`fast`, `narrative`) and exposed on `/metrics` and in the report.

## Testing
Unit tests per kind against the example documents (the compiler must regenerate `examples/valid/overlays.jsonl` semantically). Property tests for the resolver. A gate test: feed it a rejected claim and confirm only a `dropped / unverified` record appears. Latency test with a fake clock.
