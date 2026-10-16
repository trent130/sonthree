# Spec 06: Eval harness (mutator, set builder, harness, report)

Produces the Verifier numbers that go in the pitch. Integrity matters more than size.

## User stories
- As a judge, I want Verifier numbers I can reproduce from the repo.
- As the developer, I want to tune on dev and be unable to fool myself on test.

## Requirements

### 1. Mutator
1.1 THE mutator SHALL implement all 15 corruption operators from `common.schema.json` (`x-corruption-operators`), each changing exactly one thing and producing a schema-valid claim.
1.2 GIVEN a seed THE mutator SHALL be deterministic.
1.3 WHEN an operator cannot apply to a claim (for example `flip_trend` on an `event_occurred` claim) THEN the mutator SHALL skip it explicitly and SHALL NOT emit a no-op.

### 2. Set builder
2.1 THE builder SHALL generate clean labels from verified claims produced on generator matches, corrupted labels from clean ones with every operator, and SHALL support adding hand-written labels from a directory of YAML files.
2.2 EACH corrupted label SHALL share its base label's split and SHALL pass the semantic rules enforced by `check_eval_set`.
2.3 THE full set SHALL contain at least 25 test-split labels per operator and at least 150 clean test-split labels, built from matches not used for the dev split.
2.4 THE builder SHALL write `labels.jsonl` and `manifest.json` (hashes, counts, `set_version`) and the output SHALL pass `validate.py --eval`.
2.5 THE builder SHALL include hand-written false-positive traps (tolerance boundaries, equal salience ties, claims exactly at the as-of boundary) in the test split.

### 3. Harness
3.1 THE harness SHALL run any Verifier implementation (module path) on every label's claim against the manifest's streams and compare to `expected`.
3.2 THE harness SHALL compute catch rate, false-reject rate, precision, attribution accuracy (primary code in the observed codes), and rewrite success within 3 attempts using the real Narrator in replay or live mode, each by operator, by difficulty and overall.
3.3 THE harness SHALL report the `dev` and `test` splits separately and SHALL refuse to print a `test` number unless the manifest `set_version` and Verifier version are recorded with it.
3.4 THE harness SHALL be reproducible: the same set, Verifier version and cassettes produce identical metrics.
3.5 WHEN a label's outcome differs from `expected` THEN the harness SHALL list it with the claim, expected verdict and observed verdict.

### 4. Foundry mirror
4.1 THE harness MAY upload results to a Foundry project as a dataset evaluation with a code-based evaluator that scores 1.0 when the observed status matches the expected one.
4.2 THE Foundry upload SHALL be best-effort: its failure SHALL NOT fail the run and SHALL NOT change any published number, because the feature is in preview.

### 5. Report
5.1 THE harness SHALL write `docs/eval-report.md` with the set version, Verifier version, dev and test tables, per-operator results and the list of failures.
5.2 THE report SHALL state plainly which operators are deterministic-class and which are judge-class.

### 6. Discipline
6.1 THE repository SHALL treat the `test` split as read-only after the first Verifier freeze: changing a test label requires a new `set_version` and a note in the report.
