# Spec 04: Agent pipeline (Interpret and Explain, model half)

The multi-agent system that the "Best Multi-Agent Orchestration" prize is judged on: distinct roles, shared state, handoffs, failure recovery, and an outcome a single agent could not match.

## User stories
- As a broadcaster, I want commentary that is insightful and also provably supported.
- As a judge, I want to see specialized agents hand off work and recover from failure.
- As a Swahili-speaking fan, I want the same insight in my language, reviewed by a human before it is shown.

## Roles

| Role | Kind | Job | Output |
|---|---|---|---|
| Rules Analyst | code | deterministic triggers (goal, high-xG shot, threshold crossings, period summaries) | claims |
| Insight Analyst | LLM agent with tools | finds what matters beyond the rules (control shifts, pressing spells, causal chains) | claims |
| Narrator | LLM agent | writes the English rendering of a claim | claim revision or superseding claim |
| Verifier | spec 03 | accepts or rejects | verdicts |
| Translator | LLM agent | adds `sw` and `fr` renderings | claim revisions |
| Recap Editor | LLM agent | selects and orders verified claims, proposes recap-level claims | recap, claims |

## Requirements

### 1. Claim production
1.1 THE Rules Analyst SHALL turn each trigger into a claim whose assertion, evidence and rendering are produced by templates, with no model call.
1.2 THE Insight Analyst SHALL use tools to read snapshots and events and SHALL propose claims through a `propose_claim` tool that validates against the claim schema and rejects invalid proposals back to the model with the errors.
1.3 THE code, not the model, SHALL set `schema_version`, `claim_id`, `match_id`, `as_of_seq`, `produced_by` and `salience` bounds; the model supplies only the assertion, evidence and a draft rendering.
1.4 THE Insight Analyst SHALL only propose a `causal_explanation` for cause and effect claims that a registered causal pattern (spec 03) can link, using the `causal_pattern_matches` tool.

### 2. Narration
2.1 WHEN a claim needs better wording THEN the Narrator SHALL produce only the English rendering text and SHALL NOT change the assertion, evidence or dependencies.
2.2 THE system SHALL form the new claim by code, with `supersedes` set to the original, and send it to the Verifier.
2.3 WHEN the Verifier rejects a claim THEN the Narrator SHALL receive the `failure_codes`, failed checks and `rewrite_hint` and SHALL produce a rewrite, up to 3 attempts per lineage.
2.4 WHEN the third attempt is rejected THEN the system SHALL abandon the lineage, record why, and SHALL fall back to the claim's template rendering if one exists and verifies.

### 3. Translation
3.1 WHEN a claim is verified in English THEN the Translator SHALL add renderings for each language in the active profiles, each with `origin: translated` and `human_reviewed: false`.
3.2 THE Verifier SHALL check each translation; a failed translation SHALL be retried up to 2 times and otherwise omitted, never shown unverified.
3.3 THE system SHALL load a glossary of football terms in each language (`config/glossary.<lang>.json`) and pass it to the Translator.
3.4 THE system SHALL provide a review tool that lists unreviewed renderings and sets `human_reviewed` through an append-only claim revision recording who reviewed it.

### 4. Orchestration
4.1 THE pipeline SHALL be a Microsoft Agent Framework workflow with explicit handoffs: Analyst → Narrator → Verifier, a conditional edge from Verifier rejection back to the Narrator, and a branch from verified claims to the Translator and the overlay compiler.
4.2 Agents SHALL coordinate only through documents in the Store and on the bus, never by sharing prompts or memory.
4.3 THE pipeline SHALL process claims for different triggers concurrently and SHALL keep claims for one lineage strictly ordered.

### 5. Failure recovery
5.1 WHEN a model call fails or times out THEN the stage SHALL retry with backoff, and after the limit SHALL release the work item back to the queue with the failure recorded, not drop it.
5.2 WHEN the judge circuit breaker is open (3 consecutive failures) THEN the pipeline SHALL continue running the deterministic fast path only and SHALL mark LLM-dependent items pending.
5.3 THE pipeline SHALL be restartable from the Store: after a crash it SHALL resume without duplicating claims or verdicts.

### 6. Tiers and latency
6.1 THE fast path (rules claims with template renderings) SHALL reach a verified verdict within 1.5 s at the 95th percentile of the trigger event.
6.2 THE narrative path (Insight Analyst plus Narrator) SHALL reach a verified verdict within 8 s at the 95th percentile at 1x replay, matching the lower-third wait limit.
6.3 EVERY stage SHALL emit spans so each claim's timing is reconstructable.

### 7. Recap
7.1 THE Recap Editor SHALL read `match-state` and its key moments, choose and order sections, and build `text` only by joining the claims' renderings, as `check_recap` requires.
7.2 WHEN the Recap Editor wants a new statement (for example a half-time summary) THEN it SHALL propose it as a claim with agent `recap_editor` that goes through the Verifier first.

### 8. Offline operation
8.1 THE whole pipeline SHALL run in `replay` LLM mode from cassettes, producing identical output across runs, so CI and the fallback recording need no model access.
