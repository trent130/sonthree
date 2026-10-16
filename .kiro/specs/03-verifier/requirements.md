# Spec 03: Verifier

The component that makes the pitch true. It decides whether a claim may reach the screen. It is mostly deterministic code with a small, tightly scoped model-based judge.

## User stories
- As a studio producer, I want to know every statement on screen was checked against the event log.
- As a judge, I want measured catch and false-reject rates I can reproduce.
- As the Narrator, I want a precise reason when a claim is rejected, so a rewrite can succeed.

## Requirements

### 1. Verdicts
1.1 WHEN given a claim THEN the Verifier SHALL produce a verdict that passes `validate_verdict` and whose `claim_id`, `match_id` and `attempt` are correct.
1.2 THE verdict SHALL list every applicable check with `pass`, `fail` or `skipped`, and `skipped` SHALL be used only when a check does not apply to the claim kind.
1.3 THE verdict SHALL record `verifier.version`, `stats_engine_version` and the judge deployment name, and SHALL measure `latency_ms`.
1.4 WHEN a check fails THEN the verdict SHALL be `rejected`, SHALL list the matching `failure_codes`, and SHALL include a `rewrite_hint` that names the specific discrepancy.

### 2. Deterministic checks (no model involved)
2.1 `evidence_resolves`: every `event` ref exists in the stream, every `seq_range` is valid and inside the stream, every `metric_snapshot` exists with the stated `as_of_seq`.
2.2 `evidence_within_as_of`: no evidence seq, snapshot or window end is newer than the claim's `as_of_seq`.
2.3 `evidence_supports_assertion`: the cited evidence supports the assertion kind as defined in `design.md`.
2.4 `assertion_numeric_match`: for `metric_value`, `metric_comparison` and `metric_trend`, the value recomputed with `stats_ref` satisfies the assertion.
2.5 `causal_precedence`: for `causal_explanation`, `depends_on` equals cause and effect, both dependencies have a latest verdict of `verified`, and the cause window ends no later than the effect window.
2.6 `causal_plausibility`: a causal claim passes only if a registered causal pattern matches the underlying event chain (see `design.md`). No pattern means rejected with `unsupported_causal`.
2.7 `rendering_entails_assertion` (numeric part): every number in a rendering SHALL appear in the assertion or in recomputed values, and no player, team or time reference SHALL contradict the assertion.

### 3. Judge checks (model involved)
3.1 THE judge SHALL be used only for `rendering_entails_assertion` (wording that adds or contradicts detail) and `translation_fidelity` (non-numeric drift), and SHALL receive the structured assertion, the verified facts and the text, never the Narrator's reasoning.
3.2 THE judge SHALL return structured output validated against a schema and SHALL be run with temperature 0 and a different deployment from the Narrator.
3.3 IF the judge is unavailable or times out after retries THEN the Verifier SHALL emit no verdict, leave the claim pending, and retry, and SHALL NOT emit `verified` or an invented failure.
3.4 THE deterministic layer SHALL run first, and the judge SHALL NOT be called for claims already rejected by it.

### 4. Ordering and idempotence
4.1 WHEN a causal claim arrives before its dependencies are verified THEN the Verifier SHALL wait for them or verify them first.
4.2 WHEN the same claim is submitted twice THEN the Verifier SHALL return the existing verdict and SHALL NOT create a duplicate.
4.3 THE Verifier SHALL append verdicts to the Store and publish them on `verdicts`; it SHALL NOT modify claims.

### 5. Languages
5.1 FOR every non-English rendering THE Verifier SHALL run `translation_fidelity` with the rendering's `lang`, comparing numbers, names and shirt numbers deterministically and meaning through the judge.
5.2 THE Verifier SHALL never set `human_reviewed`; that field is changed only by a human review step.

### 6. Measured quality (against spec 06)
6.1 FOR operators whose failure is deterministic (`perturb_value`, `swap_player`, `swap_team`, `shift_window`, `flip_comparison`, `flip_trend`, `drop_primary_evidence`, `redirect_evidence`, `cite_future_event`, `fabricate_evidence_id`, `reverse_causal_order`, `invent_causal_link`) THE catch rate on the dev and test splits SHALL be 100 percent.
6.2 THE false-reject rate on `generated_clean` and verified `hand_written` labels SHALL be 0 percent.
6.3 FOR judge-dependent operators (`embellish_rendering`, `contradict_rendering`, `drift_translation`) the targets SHALL be set after the first dev run and recorded in `docs/eval-report.md`. No number SHALL appear in the pitch before it comes from the test split.
6.4 THE Verifier SHALL meet a median latency of under 150 ms for deterministic-only claims and under 3 s for judged claims.
