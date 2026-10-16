# Receipts: instructions for coding agents (opencode, Kiro, Copilot)

Read `.kiro/steering/*.md` first, then the spec for your lane in `.kiro/specs/<lane>/` (requirements, design, tasks). Work through `tasks.md` in order and tick boxes as you finish them.

## Hard rules

1. **`contracts/` is read-only.** Schemas, `validate.py` and `stats_ref.py` are frozen. If a contract looks wrong, stop and write the problem in `docs/contract-issues.md`. Do not edit it from a lane branch.
2. **Validate at every boundary.** Anything a service emits or stores goes through the matching `validate_*` function first. Invalid output is a bug, never something to repair silently.
3. **Fail closed.** If a claim has no `verified` verdict it is never shown, recapped or used as evidence. If a check cannot run, emit nothing and retry. Never emit a guessed verdict.
4. **Fixtures first.** Every service must run end to end on `contracts/examples/` before its upstream service exists. Build that path first.
5. **Determinism.** Same seed, same inputs, same outputs, except wall-clock fields. No unseeded randomness. LLM calls go through the cassette-capable client so tests replay offline.
6. **Synthetic data only.** Never download, embed or imitate real match data, real player names or club crests.
7. **Your acceptance test is the validator.** A lane is done when its `make accept-<lane>` target passes, not when the code looks right.

## Commands

`make setup`, `make contracts` (runs the 265-case contract suite), `make accept-<lane>`, `make accept` (all lanes), `make demo`, `make report`. Defined in spec 00.
