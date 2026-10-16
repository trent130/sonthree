# Design: Agent pipeline

## Workflow graph (Microsoft Agent Framework)
```
events/snapshots ─▶ RulesAnalyst ─┐
                 └▶ InsightAnalyst ┴─▶ claim(draft) ─▶ Verifier ──verified──▶ publish ─┬─▶ Translator ─▶ Verifier ─▶ publish
                                              ▲            │                            └─▶ overlay compiler (spec 05)
                                              │         rejected(codes, hint)
                                              └─ Narrator ◀┘   (max 3 attempts, then template fallback or abandon)
Recap: matchstate ─▶ RecapEditor ─▶ recap (+ recap claims ─▶ Verifier)
```
Use the framework's workflow engine for the graph, sequential and handoff patterns for the main path, and concurrent execution for the two analysts and for per-language translation. Confirm the exact workflow API against the current docs on day one. Keep each agent's logic in plain functions behind an `Agent` protocol, so a framework change affects only `workflow.py`.

## Agents and tools
- **Rules Analyst** is code: `triggers.py` (goal, shot with xG at or above 0.25, speed or distance threshold notice, period summary, lead change) and `templates.py` (English templates, reviewed Swahili and French templates for the same kinds, so the fast path can ship already-translated and reviewed text).
- **Insight Analyst** tools: `get_snapshot(window, subjects, metrics)`, `list_events(types, window, subject)`, `causal_pattern_matches(window)`, `propose_claim(claim_draft)`. The system prompt states the assertion vocabulary, the as-of rule and the no-new-facts rule. It sees only data up to the current `as_of_seq`.
- **Narrator** input: assertion, the verified facts the Verifier would use, profile mode for tone (casual or analyst), any `failure_codes` and `rewrite_hint`. Output schema: `{text: string}`. Length limit from the schema (400).
- **Translator** input: the verified English text, the assertion, target language, glossary. Output `{text}`; numbers, names and shirt numbers must survive unchanged (the Verifier checks).
- **Recap Editor** tools: `get_match_state`, `get_claim(id)`, `propose_recap(sections)` (validated by `check_recap`), `propose_claim`.

## Shared state
All coordination goes through the Store and bus. Claims are immutable; a Narrator rewrite is a new claim with `supersedes`; translations and reviews are claim revisions (renderings only). A `work_items` table (not an audit document) tracks stage, attempts and lease for restartability.

## Failure handling
Per-stage timeouts and retries come from `services.common`. A circuit breaker wraps the judge and the model deployments; open breaker means fast-path only. After a crash, in-flight work items whose lease expired are re-leased; idempotent id allocation and verdict idempotence prevent duplicates.

## Personas
Mode changes Narrator tone and which claims are drafted (`analyst` allows metric and trend claims, `casual` prefers events and plain wording). It never changes facts; the same verified claims feed every persona.

## Observability
Spans: `interpret` (trigger to claim), `explain` (claim to verified), `verify` (inside explain), `render` (spec 05). Each carries claim lineage id. A trace of a rejected-then-rewritten claim is the centerpiece of the demo.

## Testing
Unit tests per tool and per template. Workflow tests in replay mode over the demo match: expected counts of claims, rewrites and abandoned lineages; assert zero invalid documents on every topic; a fault-injection test (judge down, model timeout, crash and restart) with the invariants "no duplicate documents, no unverified claim eligible".
