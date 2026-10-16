# Design: Generator

## Approach
Event-driven simulation with kinematic tracking: a possession state machine decides what happens, a spatial model decides where, and a movement model keeps the 22 players and the ball consistent between events.

```
Match clock ─▶ PossessionMachine ─▶ ActionSampler ─▶ Event emitters (pass, shot, tackle, pressure, foul, card, sub)
                     │                    │
                     ▼                    ▼
               MomentumProcess      MovementModel ─▶ TrackingEmitter (frames at tracking_hz)
```

- **RNG:** one master seed; each subsystem gets `random.Random(sha256(f"{seed}:{name}"))` so changing one subsystem does not reshuffle the others.
- **Teams:** two fictional squads with formation templates (4-4-2, 4-3-3). Players have role anchors and simple attributes (pace, passing, finishing) drawn from the seed.
- **MomentumProcess:** a bounded mean-reverting random walk per team that raises or lowers action rates. It creates the control swings the control index reports.
- **PossessionMachine:** states `build_up`, `progression`, `final_third`, `shot`, `lost`. Transition probabilities depend on zone, momentum, and nearest-defender pressure from the previous frame.
- **ActionSampler:** passes (length, height, success from distance and pressure), shots (location from the final-third zone, outcome from xG), tackles and pressure events (from defender proximity), fouls (rate rises with tackles lost), cards (from fouls).
- **xG model `receipts-xg-1`:** logistic in shot distance and shot angle, calibrated so mean xG per shot is near 0.10. Constants live in `xg.py` with a test of the calibration.
- **MovementModel:** each tick every player steers toward a target (role anchor shifted toward the ball, or a marking target), with max speed and acceleration limits. The ball follows event-to-event interpolation (pass arcs with `z`, carries at player speed). Reported `speed_kmh` is computed from the simulated velocity.
- **Pacing:** `stream` mode wraps the iterator with a clock; `speed` scales the wall delay; `emitted_at` is the publish time.

## Target ranges for the realism report
Initial targets from commonly cited top-flight aggregates. Confirm them against public summary statistics, record the sources in the report, and change a range only with a written reason.

| Metric | Per match unless noted | Target range for the batch mean |
|---|---|---|
| Goals (both teams) | | 2.4 to 3.2 |
| Shots per team | | 9 to 15 |
| Mean xG per shot | | 0.08 to 0.12 |
| Pass completion | per team | 78% to 88% |
| Passes per team | | 350 to 600 |
| Possession | share, 90% of matches | 35% to 65% |
| Fouls per team | | 8 to 14 |
| Yellow cards (both teams) | | 2 to 5 |
| Red cards (both teams) | | up to 0.15 |
| Top player speed | | 30 to 36 km/h |

The data is synthetic, so only distributions are compared, never real match data.

## CLI
```
python -m generator generate --seed 7 --minutes 90 --hz 5 --out out/match_7.jsonl
python -m generator stream   --seed 7 --speed 20 --from-seq 1 --sink local|eventhubs
python -m generator report   --seeds 1-200 --out docs/data-validation.md
python -m generator find-demo-seed --seeds 1-500
```

## Size note
A 90-minute match at 5 Hz has about 28,000 frames of up to 22 players, tens of MB of JSONL. Default to 5 Hz for the demo clip and allow 2 Hz for full-match batch runs. `tracking_hz` is a metadata field, so downstream code is unaffected.

## Testing
Unit: xG calibration, speed consistency, ball-to-event distance, possession id coverage. Property: 50 random seeds pass `validate.py` and determinism. Golden: the demo seed's first 20 minutes checked into `tests/golden/` by hash.
