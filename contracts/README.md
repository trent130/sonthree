# Receipts contracts v1

Frozen interfaces between the five pipeline stages. Every cross-stage payload is validated against these schemas at the boundary. Producers fail closed.

```
generator ──event──▶ stats engine ──┐
                                    ├─▶ Analyst ──claim──▶ Narrator ──claim──▶ Verifier ──verdict──▶ audit log
generator ──event──▶ Analyst  ──────┘                                              │
                                                              verified claims ─────┴─▶ overlay compiler ──overlay──▶ renderer
                                                                                       personalizer ──profile──▶ (filters, language)
generator ──event──▶ stats engine ──snapshot──▶ overlays, claims, match state ──▶ Recap Editor ──recap──▶ frontend
```

## Files

| File | What it defines | Who produces | Who consumes |
|---|---|---|---|
| `schemas/common.schema.json` | ids, pitch geometry, clock, metric registry with units (`x-metric-units`), failure codes | none | all |
| `schemas/event.schema.json` | one JSONL line of the match stream, 12 event types | generator | stats engine, Analyst, Verifier, overlay compiler |
| `schemas/claim.schema.json` | atomic assertion + evidence + renderings | Analyst, Narrator, Recap Editor | Verifier, audit log, overlay compiler, frontend chips |
| `schemas/verdict.schema.json` | Verifier result for one attempt on one claim | Verifier | Narrator (rewrite loop), audit log, evals |
| `schemas/eval-label.schema.json` | one Verifier test case: a claim plus the verdict a correct Verifier must return | eval-set builder, hand authors | Verifier eval harness (Foundry) |
| `schemas/eval-manifest.schema.json` | pins an eval set to exact bytes (labels and event streams, by sha256) | eval-set builder | eval harness, README numbers |
| `schemas/snapshot.schema.json` | deterministic metric values for one window, cited by `snap_` id | stats engine | claims, overlays, match state, Verifier |
| `schemas/profile.schema.json` | personalization preferences: mode, language, favorites, focus, overlay density | frontend / personalizer | overlay compiler, recap editor |
| `schemas/match-state.schema.json` | derived view: status, score, snapshot, ranked key moments | stats engine | Recap Editor, personalizer |
| `schemas/recap.schema.json` | half-time or full-time recap built only from verified claims | Recap Editor | frontend |
| `schemas/overlay.schema.json` | one timed, resolved overlay instruction: lower third, stat card, momentum bar, player tag | overlay compiler | renderer, frontend replay, latency dashboard |
| `stats_ref.py` | the executable metric definitions; `STATS.md` is its prose spec | | stats engine, Verifier, validator |
| `STATS.md` | exact formulas, windows, rounding and undefined-value rules for all 20 metrics | | stats engine authors |
| `validate.py` | schema validation plus semantic checks, including recomputing every snapshot value | | CI, every service boundary |
| `test_contracts.py` | 265 test cases (136 test functions; parametrized corruptions make up the rest): fixtures pass, targeted corruptions fail, metrics match hand calculations | | CI |
| `tools/make_example_state.py` | builds the snapshot, profile, match-state and recap fixtures from `stats_ref.py` and wires claims and overlays to them | | fixtures |
| `tools/make_example_evalset.py` | builds the example eval set from the valid fixtures with one small corruption operator per label; the seed of the real mutator | | eval-set builder |
| `examples/eval/*` | 14 labels (8 corrupted, 4 clean, 2 hand written) across dev and test, plus the manifest | | Kiro specs, tests |
| `examples/valid/*` | 16-event stream, 5 claims (one rewrite), 5 verdicts, 6 overlays (one dropped as unverified, one dropped on collision), 4 snapshots, 2 profiles, a half-time match state and recap, all cross-referencing each other | | Kiro specs, tests |

Run `pip install -r requirements.txt && pytest -q`, then validate the whole example run:

```
python validate.py examples/valid/match_stream.jsonl \
  --claims examples/valid/claims.json --verdicts examples/valid/verdicts.json \
  --overlays examples/valid/overlays.jsonl --snapshots examples/valid/snapshots.json \
  --profiles examples/valid/profiles.json --state examples/valid/match_state.json \
  --recap examples/valid/recap.json --require-reviewed
python validate.py --eval examples/eval/manifest.json     # eval set, including hashes
```

`--require-reviewed` fails any shown overlay or recap whose non-English text has not been human reviewed (the demo gate for Swahili). Regenerate fixtures in this order: `make_example_stream.py`, `make_example_state.py`, `make_example_evalset.py`.

## Conventions

- **Schema dialect:** JSON Schema draft 2020-12. Ids are `urn:receipts:schema:v1:<name>`; schemas reference each other by those URNs, so no network access is needed.
- **Strictness:** every object is closed (`additionalProperties: false`, or `unevaluatedProperties: false` on event variants). Unknown fields are errors.
- **Clock:** `match_time_ms` is one continuous clock, stoppage included, never reset between periods. `seq` orders events; `period` 0 is metadata only.
- **Pitch:** meters, 105 x 68, origin bottom-left, absolute coordinates. Which way the home side attacks is declared per period in `period_start.payload.home_attacking_towards`. Nothing is flipped per team.
- **Ids:** `ev_0000015` = seq 15 (enforced), `cl_` claims, `vd_` verdicts, `p_` players, `t_` teams, `pos_` possession spells, `snap_` stats snapshots.
- **Synthetic guard:** `match_metadata.payload.synthetic` must be `true`. Real data cannot validate.
- **Determinism:** a seed reproduces the stream exactly, except `emitted_at` (wall clock, used only for latency).

## How the contracts enforce "explainability by construction"

1. **Claims are typed, not prose.** Five assertion kinds (`event_occurred`, `metric_value`, `metric_comparison`, `metric_trend`, `causal_explanation`) that code can check against the event log and the stats engine. The English text is a rendering of the assertion, and the Verifier checks that it adds nothing.
2. **No future leaks.** Every claim has `as_of_seq`. Evidence newer than that, or a window that ends after that event's time, is rejected. This also keeps the live narration honest.
3. **Causal claims are links, not stories.** `causal_explanation` points at two other claims that must each verify, with the cause ending no later than the effect. Unsupported "because" statements cannot be expressed.
4. **Everything is auditable.** Claims are immutable (a rewrite is a new claim with `supersedes`). Verdicts are append-only, one per attempt, with per-check results and shared `failure_codes`.
5. **Translations are first-class.** Renderings carry `origin` and `human_reviewed`, and the Verifier has a `translation_fidelity` check per language.
6. **Nothing unverified reaches the screen.** A shown overlay may only cite claims whose latest verdict is `verified` and which no rewrite has superseded. A rejected claim can appear in the overlay log only as `dropped / unverified`. `validate.py` enforces this, so "zero unverified claims displayed" is a number you can report.

## Overlays

The overlay stream is a **resolved timeline**: the compiler has already decided collisions, and every decision is in the log.

| Kind | Source it must cite | Payload | Renders from |
|---|---|---|---|
| `lower_third` | exactly one claim | kicker, text, up to 3 highlighted players | the claim's rendering in the overlay's `lang` (text must be identical) |
| `stat_card` | 1-4 `metric_value` claims | per metric: claim, subject, metric, value, unit | the claims' typed assertions, no English parsing; value must satisfy the claim and unit must match the registry |
| `momentum_bar` | a stats snapshot (no claims) | one index, window, a value for each team | the stats engine's control, pressure or rhythm index |
| `player_tag` | optional snapshot | player, optional speed or distance indicator with threshold and observed value | the player's position in the tracking frames; indicator observed must reach its threshold |

**Timing.** `trigger_seq` is the event that caused the overlay. It must be at or after every cited claim's `as_of_seq`, and `start_ms` can never be earlier than that event's own time. `start_ms` is on the match clock, so a replay or a live feed can sync to it.

**Collision policy v1** (constants live in `validate.py`; changing them is a policy change, not a schema change):

| Kind | Concurrent slots | Max wait after trigger event |
|---|---|---|
| `lower_third` | 1 | 8000 ms |
| `stat_card` | 1 | 8000 ms |
| `momentum_bar` | 1 | 3000 ms |
| `player_tag` | 3 | 2000 ms |

- `scheduled`: shown for its full duration.
- `preempted`: shown until `displaced_by` starts. The displacer must be the same kind, start during the overlay, and have priority at or above it (ties go to the newer overlay).
- `dropped`: never shown, kept for audit, with a reason. `collision` requires every slot to be full at its start time with occupants of equal or higher priority. `stale` requires a wait over the limit. `unverified` requires at least one cited claim without a verified verdict.
- `priority` is the claims' salience x 100, adjusted by the compiler if needed. Momentum bars and tags without claims set it directly.

**Latency measurement point.** Each overlay may carry `latency`: `event_emitted_at` (copied from the trigger event), `compiled_at`, and a per-stage breakdown (`interpret`, `explain`, `verify`, `render`). Event-to-overlay latency is `compiled_at - event_emitted_at`. The validator checks the copy matches the event, time does not run backwards, and the stages cannot sum to more than the total. The frontend can add its own receive timestamp to get true on-screen latency.

**Dependency:** overlays cite `snap_` ids for stats-engine numbers, but the snapshot document itself is defined with shared state (next). Until then `snapshot_id` is an opaque, format-checked reference.
## Metric registry (`common.MetricId`)

Exact formulas, windows, rounding and undefined-value rules are in **`STATS.md`**, and `stats_ref.py` is the executable version that the stats engine, the Verifier and the validator all import. The table is the summary.

| Metric | Unit | Definition |
|---|---|---|
| `goals` | count | shots with outcome `goal` |
| `shots` | count | shot events |
| `shots_on_target` | count | shots with outcome `goal` or `saved` |
| `xg` | xG | sum of `shot.xg` |
| `passes` | count | pass events (attempted) |
| `pass_accuracy_pct` | % | `complete` / attempted x 100 (`out_of_play` counts as not complete) |
| `avg_pass_length_m` | m | mean distance `location` to `end_location` over attempted passes |
| `avg_pass_difficulty` | 0-1 | mean of 0.4 x length + 0.2 x height + 0.2 x forward progress + 0.2 x nearest-defender pressure (see STATS.md) |
| `possession_pct` | % | share of the window the team held possession, from `possession_change` spans |
| `tackles_won` | count | tackle events with outcome `won` |
| `pressures` | count | pressure events by the pressing team |
| `ppda` | ratio | opponent passes starting 42 m or more from their own goal line / the team's tackles, pressures and fouls in that same zone |
| `control_index` | 0-100 | 100 x (0.6 x possession share + 0.4 x share of possession spells lasting 8 s or more) |
| `pressure_index` | 0-100 | tackles + pressures + fouls per minute, scaled so 6 per minute = 100 |
| `rhythm_index` | 0-100 | passes + shots + tackles + fouls per minute, scaled so 30 per minute = 100 |
| `distance_km` | km | integral of tracked player position |
| `top_speed_kmh` | km/h | max tracked player speed |
| `sprints` | count | runs of at least 1 s at 25 km/h or more |
| `max_ball_speed_kmh` | km/h | max tracked ball speed |
| `max_shot_speed_kmh` | km/h | max `shot.ball_speed_kmh` |

## Shared state

**Snapshot.** The stats engine's output for one window: a list of `{subject, metrics}`. Anything shown with a stats number cites a snapshot by `snap_` id. The validator **recomputes every value** with `stats_ref.py` and fails any that disagree beyond rounding, so a snapshot cannot carry a number the event stream does not support. It also checks that each metric is allowed for its subject type, that undefined metrics are not listed, and that the window ends at or before the as-of event.

How snapshots connect to the rest:
- A `metric_value` claim that cites a snapshot must match it: same subject, metric and window, and the snapshot value must satisfy the assertion. The snapshot cannot be newer than the claim.
- A momentum bar must show exactly the snapshot's index for each team over the snapshot's window.
- A distance or speed indicator on a player tag must equal the snapshot value or, for speed, the trigger tracking frame.

**Profile.** Preferences only, no personal data: `mode` (casual, analyst, broadcaster), `lang`, up to 2 favorite teams and 3 favorite players, a `focus` (whole match, one player, or one metric) and an overlay `density`. Enforced rules: an overlay with a `profile_id` must use the profile's language, and a shown overlay must meet the density floor (minimal 70, standard 40, rich 0). Favorites and focus must exist in the match. How favorites and focus raise `priority` is compiler policy: the suggested boosts are +15 for a claim about a favorite or the focus player and +10 for a claim about the focus metric, capped at 100, but only the resulting `priority` is validated.

**Match state.** A materialized, fully re-derivable view so the Recap Editor does not recompute: `status` (from the last period event), `score` (recounted from goal shots), the whole-match `snapshot_id`, and `key_moments`. Key moments must be exactly the top of the eligible claims (verified, not superseded, known at `as_of_seq`), ordered by salience then claim id. A stale or hand-picked list fails.

**Recap.** Half-time or full-time, a few titled sections, each a list of claim ids plus `text`. The text must be those claims' renderings in the recap's language, joined by single spaces. The Recap Editor therefore **selects and orders verified claims; it cannot introduce a new fact**. Any new recap-level statement is first a claim from `recap_editor` and goes through the Verifier like every other. A recap is held to the same gates as overlays: verified, not superseded, and no unreviewed non-English text under `--require-reviewed`. When a match state is supplied, the recap must use the state's `as_of_seq`, match its status, and only use its key moments.

## Verifier eval set

The published Verifier numbers come from this format, so every rule below exists to keep them honest and reproducible.

**A label is a full claim plus the verdict a correct Verifier must return** (`expected.status`, `failure_codes`, `failed_checks`, and for rejected claims `rewritable`). The claim is a complete claim document, so the Verifier is tested on exactly what it sees in production. Every corrupted claim is schema-valid; the schema cannot catch it, the Verifier has to.

**Origins**
- `generated_clean`: a true claim, expected `verified`.
- `generated_corrupted`: one corruption operator applied to a clean label, expected `rejected`. The label records the operator and its base label.
- `hand_written`: any status. Use these for false-positive traps (a claim sitting exactly on its tolerance boundary must verify) and for real failures seen during development.

**Corruption operators** (each provokes one primary failure code; extra codes may also be expected)

| Operator | Primary code | Reported by check |
|---|---|---|
| `swap_player`, `swap_team`, `shift_window` | `wrong_player`, `wrong_team`, `wrong_time_window` | `evidence_supports_assertion` |
| `perturb_value`, `flip_comparison`, `flip_trend` | `wrong_value`, `wrong_comparison`, `wrong_trend_direction` | `assertion_numeric_match` |
| `drop_primary_evidence`, `redirect_evidence` | `missing_evidence`, `evidence_irrelevant` | `evidence_supports_assertion` |
| `fabricate_evidence_id` | `evidence_not_found` | `evidence_resolves` |
| `cite_future_event` | `future_leak` | `evidence_within_as_of` |
| `invent_causal_link`, `reverse_causal_order` | `unsupported_causal`, `causal_order_violation` | `causal_plausibility`, `causal_precedence` |
| `embellish_rendering`, `contradict_rendering` | `rendering_adds_detail`, `rendering_contradicts` | `rendering_entails_assertion` |
| `drift_translation` | `translation_drift` | `translation_fidelity` |

The operator-to-code and code-to-check tables live in `common.schema.json` (`x-corruption-operators`, `x-failure-code-checks`), so the mutator, the Verifier and the validator share one source. `schema_invalid` never appears in labels.

**Integrity rules the validator enforces**
- A label expected `verified` must pass every deterministic check (`check_claims`). A label expecting `future_leak`, `evidence_not_found` or `causal_order_violation` must actually trip the deterministic layer, so a label cannot claim a corruption it does not contain.
- A corrupted claim must differ from its base, and it must share the base's `split`. Otherwise a test label would be a near-copy of a dev label you tuned on.
- Expected failed checks must be explained by the expected codes, and every expected code must have its reporting check in `failed_checks`.
- The manifest pins `labels.jsonl` and every event stream by sha256, so a changed byte fails validation. Publish numbers only with a `set_version`.

**Scoring (what the harness computes).** "Positive" means the Verifier rejected the claim.
- **Catch rate** (recall): rejected among labels expected `rejected`.
- **False-reject rate**: rejected among labels expected `verified`. Precision follows from the two.
- **Attribution accuracy**: among correctly caught claims, the primary failure code appears in the Verifier's codes.
- **Rewrite success**: among rejected, `rewritable` labels, the share whose Narrator rewrite is verified within 3 attempts.
- Report each by operator and by `difficulty`, and **quote the `test` split only**. Tune on `dev`.

The Verifier verdict schema and this scoring share `FailureCode` and `CheckId`, so an eval run is just verdicts compared to `expected`.

## Versioning

- `schema_version` is `1.minor.patch` on every document. Validators accept `1.x.x`.
- **Minor:** additive only (new optional field, new enum value, new metric). Because objects are closed, a minor bump means consumers must update their copy of the schemas; roll schemas and services together from this repo.
- **Patch:** description and clarification changes only.
- **Major:** any removal, rename, tightening of an existing field, or semantic change. New `$id` (`...:v2:...`), side-by-side during migration.
- Changing a metric formula changes `stats_engine_version`, not the schema. The Verifier records both versions in every verdict.

## Decisions I made that you should review

1. **`seq` and `event_id` carry the same number.** Redundant on purpose: `seq` for range math, `event_id` as the human-readable cite string. Enforced equal. Drop one if you dislike the redundancy.
2. **Tracking frames share the event stream and consume `seq`.** Simple and replayable, but a 90-minute match at 5 Hz makes the stream mostly frames and evidence ranges include them. Alternative: a separate frame stream keyed by `match_time_ms`.
3. **The generator emits `xg` as ground truth** (`xg_model` names the model). The stats engine sums it, it does not recompute it.
4. **Closed assertion vocabulary.** Five kinds. It limits what the Analyst can say, but anything outside it cannot be verified deterministically anyway. Add kinds as minor bumps.
5. **A window must be closed by the as-of event time.** "The first 30 seconds" cannot be asserted at 20 seconds in. This is stricter than most live systems; it is what makes the future-leak check meaningful.
6. **Renderings live inside the claim and are append-only** (translations are added later). Alternative: separate rendering documents. Inline is easier for the frontend; separate is cleaner for audit.
7. **Analyst emits claims directly,** with a draft English rendering the Narrator may supersede. There is no separate `Finding` type.
8. **Overlay `lang` is required even for numbers-only overlays,** so one stream can be filtered per viewer. `profile_id` is optional and opaque until the profile schema exists.
9. **Collision policy lives in code, not in the schema.** Capacities and wait limits are validator constants, so you can tune them without a schema bump. The cost is that the renderer must import the same table; if you would rather ship it as data, it moves to `common.schema.json` as an `x-` annotation like the metric units.
10. **A dropped overlay still validates its text and sources** so the audit log stays coherent, but only shown overlays are held to the verified-claim gate.
11. **Labels embed the whole claim and refer to streams through the manifest, not per label.** Keeps a label self-contained for the Verifier and the stream hash in one place. Claim ids must be unique across the whole label set because causal labels reference other labels' claims.
12. **`missing_evidence` is defined as "evidence is present but lacks what the assertion needs".** The claim schema already forbids empty evidence on non-causal claims, so a literal "no evidence" claim cannot reach the Verifier. `common.FailureCode` now says so.
13. **Attribution is scored on the primary code only.** A corruption may legitimately trigger a second code; requiring an exact set would punish a correct Verifier.
14. **The reference engine is part of the contract.** `stats_ref.py` is the single implementation the stats engine and Verifier import, so "the Verifier recomputes the numbers" holds by construction. The cost is that the production engine must reuse it or match it exactly; any formula change bumps `STATS_ENGINE_VERSION`.
15. **Metric formulas are design choices, not fitted to data.** Weights (0.6 / 0.4 for control, the four difficulty terms), baselines (6 and 30 per minute), the 8 s stable spell and the 42 m pressing zone are all reasonable defaults. Review them once in STATS.md; after the Verifier exists they only change with a version bump.
16. **Indices are per team and not zero-sum,** so a momentum bar shows two independent values. If you want a single tug-of-war bar, derive it in the frontend.
17. **Match state and recap are derived, then re-checked,** not trusted. That is intentional redundancy: a state that drifts from the stream fails validation.
18. **Recap text is assembled, not authored.** It keeps the recap provably free of unverified claims. Flowing prose across sections is the Narrator's job, done by producing a verified claim first.
19. **Not modeled in v1:** own goals, penalty shootouts, VAR reviews, injuries, offsides, set-piece delivery detail. `foul`, `card` and `substitution` are in the schema but not in the example stream.

## Not in this drop

Every stage boundary now has a contract. Not here: the real services. That means the synthetic match generator, the production stats engine (it should import `stats_ref.py`), the Analyst, Narrator and Verifier agents, the overlay compiler, the real corruption mutator and the eval harness. This drop only fixes the interfaces they implement. Also not here: audio or speech output, and the data-validation report that compares the generator's output with real football distributions.
