# Spec 01: Synthetic match generator (Ingest)

The generator is a deliverable (the brief's "data innovation"), not scaffolding. It must be realistic enough that downstream stages do not look fake.

## User stories
- As a studio engineer, I want a believable synthetic match with tracking and events, so I can test the pipeline without real data.
- As a judge, I want evidence the data is realistic, so I trust the results built on it.
- As the demo operator, I want a reproducible match with interesting moments, so every take is the same.

## Requirements

### 1. Validity and determinism
1.1 WHEN run with a seed, duration and tracking rate THEN the generator SHALL emit a JSONL stream where every line passes `validate_event` and the whole stream passes `check_event_stream`.
1.2 WHEN run twice with identical parameters THEN the outputs SHALL be byte-identical except for `emitted_at`.
1.3 THE metadata event SHALL set `synthetic` true and record generator name, version and seed.
1.4 THE generator SHALL use only fictional team and player names and SHALL fail its own test if a name appears on a bundled blocklist of real clubs and players.

### 2. Football structure
2.1 THE match SHALL have a `match_metadata` event, a kick-off `possession_change`, two periods of 45 minutes plus stoppage, `period_start` and `period_end` events, and swap `home_attacking_towards` in period 2.
2.2 THE generator SHALL track possession as spells with a `possession_id`, and every pass, shot, tackle and pressure SHALL carry the `possession_id` of the spell it occurs in.
2.3 WHEN possession changes THEN a `possession_change` event SHALL precede the new team's first action and name its `cause` consistently with the preceding event (a tackle event for `tackle`, an intercepted pass for `interception`).
2.4 THE generator SHALL produce fouls, cards and substitutions at plausible rates, with every card following a foul or other cause that fits its `reason`.

### 3. Tracking consistency
3.1 THE generator SHALL emit `tracking_frame` events at `tracking_hz`, each with the on-pitch players of both teams and the ball.
3.2 FOR consecutive frames THE reported `speed_kmh` SHALL be within 15 percent of the speed implied by displacement, and no player SHALL exceed 40 km/h or leave the pitch.
3.3 WHEN a pass or shot event occurs THEN the ball position in the nearest frame SHALL be within 1.5 m of the event `location`.
3.4 THE shot `ball_speed_kmh` and `xg` SHALL be consistent with shot distance and angle under the documented `receipts-xg-1` model.

### 4. Realism
4.1 FOR a batch of at least 200 seeds THE generator SHALL produce distributions inside the target ranges in `design.md` for goals, shots, xG per shot, pass completion, passes, possession, fouls and cards.
4.2 WHEN a distribution leaves its range THEN `generator report` SHALL fail and name the metric.
4.3 THE report SHALL be committed as `docs/data-validation.md`, with the sources of the target ranges and the generator version.

### 5. Streaming
5.1 WHEN started in stream mode with a speed multiplier THEN the generator SHALL publish events to the EventBus paced against the match clock and stamp `emitted_at` with the publish time.
5.2 WHEN a start `seq` is given THEN streaming SHALL begin from that event, so a replay can seek.
5.3 THE generator SHALL support pause and resume without duplicating or dropping events.

### 6. Demo match
6.1 THE generator SHALL provide `find-demo-seed`, which ranks seeds by narrative richness (a goal in the first half, a lead change, at least one forced turnover leading to a shot, a card) and records the chosen seed in `config/demo.json`.
6.2 THE chosen demo match SHALL be a full 90 minutes and also have a pre-cut first 20 minutes for fast iteration.

### 7. Performance
7.1 THE generator SHALL produce a full 90-minute match in under 60 seconds on a laptop and stream it at up to 60x without falling behind.
