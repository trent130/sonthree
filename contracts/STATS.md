# Stats engine definitions, v0.1.0

`stats_ref.py` is the executable version of this document and wins if they ever disagree. The production stats engine and the Verifier both import it. **Changing any formula or constant bumps `STATS_ENGINE_VERSION`**, and every snapshot and verdict records the version it used.

## Inputs and conventions

- A metric is computed for a **subject** (player, team or match) over a **window** `[from_ms, to_ms]` (inclusive, match clock), using only events with `seq <= as_of_seq`.
- A snapshot's window must end at or before the time of its `as_of_seq` event, so nothing in a window can be unknown at the as-of point.
- Values are rounded to 4 decimal places. Validators accept a difference of `6e-5`.
- A metric that is **undefined** (for example pass accuracy with no passes, or `ppda` with no defensive actions) is omitted from a snapshot. It is never reported as 0.
- An event "belongs" to a player through `player_id` and to a team through `team_id`. For a tackle or pressure that is the player making it.

## Counting metrics

| Metric | Definition |
|---|---|
| `goals` | `shot` events with outcome `goal` |
| `shots` | `shot` events |
| `shots_on_target` | `shot` events with outcome `goal` or `saved` |
| `xg` | sum of `shot.xg` |
| `passes` | `pass` events, attempted |
| `pass_accuracy_pct` | 100 x passes with outcome `complete` / passes. `out_of_play` is not complete |
| `avg_pass_length_m` | mean straight-line distance from `location` to `end_location` |
| `tackles_won` | `tackle` events with outcome `won` |
| `pressures` | `pressure` events |
| `max_shot_speed_kmh` | max `shot.ball_speed_kmh` |
| `max_ball_speed_kmh` | max over tracking-frame ball speeds and shot ball speeds (match subject only) |

## Possession

Possession spans come from `possession_change` events: a span starts at the event and ends at the next `possession_change` or `period_end`. A span still open at the end of the data runs to `to_ms`. Spans are clipped to the window.

- `possession_pct` = 100 x the team's clipped span time / all clipped span time. Time with no possessor is excluded.
- A **stable spell** is a clipped span of at least 8000 ms.

## The indices (team subjects, 0 to 100)

| Metric | Formula |
|---|---|
| `control_index` | 100 x (0.6 x possession share + 0.4 x stability), where possession share = `possession_pct` / 100 and stability = stable spells / spells (0 if no spells) |
| `pressure_index` | min(100, 100 x defensive actions per minute / 6). Defensive actions = the team's tackles + pressures + fouls (any outcome) in the window |
| `rhythm_index` | min(100, 100 x on-ball events per minute / 30). On-ball events = the team's passes + shots + tackles + fouls |

The indices are per team and not zero-sum. The baselines (6 and 30 per minute) are constants, not measured from the match, so a number means the same thing in minute 3 and minute 83.

## PPDA (team subject)

For team T and opponent O: **opponent passes allowed per defensive action in the pressing zone.**

- The zone is every location at least **42 m** from O's own goal line. O's own goal line is x = 0 if O attacks +x in that period, otherwise x = 105.
- Numerator: O's passes whose start `location` is in the zone.
- Denominator: T's tackles, pressures and fouls whose `location` is in the zone.
- Undefined when the denominator is 0.

## Pass difficulty

Per pass, then averaged. All terms are in [0, 1]:

```
difficulty = 0.4 x length + 0.2 x height + 0.2 x progress + 0.2 x pressure

length   = min(pass length m / 40, 1)
height   = ground 0, low 0.5, high 1
progress = clamp(forward metres / 30, 0, 1)     forward = (end x - start x) x attack direction of the passer
pressure = 1 - min(d / 10, 1)                   d = distance from the pass start to the nearest opposing player
                                                in the latest tracking frame at or before the pass, at most
                                                1000 ms old (0 if there is no such frame)
```

## Tracking metrics (player or team subjects)

Tracking frames in the window are used. Two consecutive frames of a player are linked only if they are at most 1.5 x the frame interval (`1000 / tracking_hz` ms) apart.

| Metric | Definition |
|---|---|
| `distance_km` | sum of straight-line steps between linked frames, in km. Undefined with no linked step. A team's value is the sum over its players |
| `top_speed_kmh` | max `speed_kmh` over the subject's players and frames in the window |
| `sprints` | runs of consecutive linked frames at or above 25 km/h whose first and last frame are at least 1000 ms apart. A team's value is the sum over its players. Undefined with no frames |

## Allowed subjects

Declared per metric in `common.schema.json` (`x-metric-scope`) and enforced by the validator. Player and team: counting metrics, `avg_pass_difficulty`, `distance_km`, `top_speed_kmh`, `sprints`, `max_shot_speed_kmh`. Team only: `possession_pct`, `ppda`, and the three indices. Match only: `max_ball_speed_kmh`.

## Known simplifications

- Ball-speed and shot-speed come from the synthetic generator as given, not estimated from video. Auto-eventing from video is out of scope.
- Fouls count as defensive actions but are not otherwise modeled. Own goals, offsides and VAR are out of scope for v1.
- The baselines and weights are design choices, not fitted to real data. The data-validation report should say so.
