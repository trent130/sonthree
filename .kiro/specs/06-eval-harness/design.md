# Design: Eval harness

## Layout
```
evals/
  mutator/operators.py     15 functions: (claim, ctx, rng) -> (claim', corruption detail) | Skip
  mutator/context.py       access to the stream, roster, snapshots, sibling claims
  builder.py               produce labels, splits, manifest
  hand/                    YAML hand-written labels
  harness.py               run, compare, aggregate
  metrics.py               catch rate, false-reject rate, precision, attribution, rewrite success
  foundry.py               optional dataset upload and evaluator registration
  report.py                docs/eval-report.md
  sets/<version>/          labels.jsonl, manifest.json
```
`contracts/tools/make_example_evalset.py` is the reference for operator behavior; port it, then generalize.

## Operators (one change each, keep the claim valid)
| Operator | Change |
|---|---|
| `swap_player`, `swap_team` | replace the subject id with another real id of the match; update rendering names or numbers accordingly |
| `shift_window` | move the window so cited events fall outside it |
| `perturb_value` | change the asserted value outside tolerance, update the rendering to match |
| `flip_comparison`, `flip_trend` | invert the relation or direction; update rendering |
| `drop_primary_evidence` | remove the primary ref, keep context refs (needs two or more refs) |
| `redirect_evidence` | replace evidence with real events of another type or subject |
| `fabricate_evidence_id` | cite an id beyond the stream or an unused id inside it |
| `cite_future_event` | add an event newer than `as_of_seq` |
| `invent_causal_link` | link two true claims in the right order that no pattern supports |
| `reverse_causal_order` | swap cause and effect |
| `embellish_rendering` | add a plausible but unsupported superlative or fact |
| `contradict_rendering` | change a direction word or negate (not a number) |
| `drift_translation` | change a numeral, name or shirt number in a translation |

## Split discipline
Matches (seeds) are assigned to a split first; all labels from a match inherit it. Corrupted labels additionally share their base's split (checked by the contract). That prevents leakage at both levels.

## Metrics
- *Catch rate* = rejected / expected-rejected. *False-reject rate* = rejected / expected-verified. *Precision* = true rejects / all rejects. *Attribution* = primary code ∈ observed codes among true rejects. *Rewrite success* = rewrites verified within 3 attempts / expected-rejected labels with `rewritable` true (runs the Narrator).
- Aggregated by operator, difficulty and split. Wilson intervals are reported beside every rate so a small cell is not over-read.

## Foundry mirror
Upload a dataset of `{label_id, expected_status, observed_status, operator}` and register a code-based evaluator whose `grade(sample, item)` returns 1.0 when the two statuses match. The API is preview: wrap it in try/except, log the run URL when it works, and never gate on it.

## Testing
Operator tests (valid output, exactly one change, determinism). Builder tests (`validate.py --eval` passes, split inheritance, minimum counts). Harness tests against a fake Verifier with known confusion matrix (verifies every metric formula). Reproducibility test (run twice, compare).
