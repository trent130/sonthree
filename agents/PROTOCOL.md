# Agent protocol: implement, review, fix

One lane = one git worktree = one implementer agent. A separate reviewer context checks every task before it counts as done. The loop is the same for every lane.

## Roles

| Role | Context | May change | May not change |
|---|---|---|---|
| **Implementer** | the lane tab | source and tests in the lane's owned paths | `contracts/`, other lanes' paths, the review files |
| **Reviewer** | a fresh context (subagent or separate tab), ideally a different model | **tests only**, under `<lane dir>/tests/review/`, plus the review file | any non-test source |
| **Fixer** | the implementer, in fixing mode | same as implementer | it may not delete, skip or loosen a test without an approved entry in the review file |
| **Lane reviewer** | fresh context at the end of the lane | tests and the lane report | source |

Reviewers write failing tests; they do not rewrite the implementation. That keeps accountability clear and gives the fixer something objective to satisfy.

## Files (inside the worktree, git-ignored)

```
.agent/STATUS.md            state machine, read by the human dashboard
.agent/REVIEW-t<N>-r<K>.md  review of task N, round K
.agent/QUESTIONS.md         ambiguities and contract issues, appended by anyone
.agent/LOG.md               one line per transition (task, round, outcome, minutes)
```
At the end of the lane the implementer commits a summary to `docs/lanes/<lane>.md` (what was built, requirement coverage, known gaps).

## The task loop

For each unchecked task in `.kiro/specs/<spec>/tasks.md`, in order:

1. **Implement** (`state: implementing`). Write the tests for the task's requirements first, then the code. Run the task's tests, the lane's full test suite, `ruff`, and `make contracts`. Commit: `feat(<lane>): task N <title>`.
2. **Review** (`state: in-review`). Spawn the reviewer on the commit (`git show HEAD`) with the reviewer prompt. The reviewer writes `.agent/REVIEW-t<N>-r1.md`.
3. **Fix** (`state: fixing`, `round: K`). The implementer fixes every `blocker` and `major` finding, keeps or adds the test for each, and commits `fix(<lane>): task N round K`. Run the same checks as step 1.
4. **Re-review.** The reviewer reviews only the delta since its last review plus anything the fixes touched, and either appends `APPROVE` or new findings.
5. **Stop rules.** The task is done on `APPROVE`, then tick its box in `tasks.md` and move on. After **3 rounds** without approval, stop, set `state: blocked`, write what is unresolved in `QUESTIONS.md`, and continue with the next task that does not depend on it. A human decides.

When all tasks are ticked, run the **lane review** (below), then `state: lane-done`.

## Severity and evidence

A finding without evidence is a note, not a finding. Every `blocker` or `major` finding must carry one of: a failing test the reviewer added, a command and its output, or a quoted requirement the code demonstrably violates.

- **blocker:** violates a requirement or a contract, can emit an invalid document, can show or use an unverified claim, loses or duplicates data, breaks determinism, or breaks a previous task.
- **major:** a missing edge case that can occur in normal use, an untested requirement, an error path that swallows an error, a test that cannot fail, a performance target missed.
- **minor:** naming, structure, small clarity. Recorded, fixed only if cheap. Never loops the task.

## Reviewer checklist (project-specific, always applied)

1. **Boundaries.** Is every document written or read validated with `validate_*`? Is any invalid input dropped silently instead of failing loudly or dead-lettering?
2. **Fail closed.** Can any path treat a claim as usable without a `verified` latest verdict, or emit a verdict when a check could not run?
3. **As-of discipline.** Any use of data newer than `as_of_seq`. Off-by-one on inclusive windows. Windows ending after the as-of event.
4. **Determinism.** Unseeded randomness, dict or set ordering in output, wall-clock values leaking into documents other than `emitted_at` and `compiled_at`, locale or timezone dependence.
5. **Numbers.** Rounding differences from `stats_ref` (4 dp), integer versus float, undefined metrics returned as 0, division by zero, empty windows, a single frame.
6. **Text.** Swahili and French: UTF-8 end to end, normalization, no ASCII-only assumptions, length limits counted in characters.
7. **Append-only and idempotence.** Any update or delete of audit documents. Duplicate documents after retry or restart.
8. **Concurrency and ordering.** Per-match ordering preserved, shared mutable state, races between consumer groups, leaked tasks or open resources.
9. **Error paths.** Timeouts, retries with backoff, cancellation, a dependency down, empty input, a malformed document, a very large input.
10. **Tests.** Does each requirement for the task have a test that would fail if the code were wrong? Break the code on purpose (comment out a condition, flip an operator) and confirm a test fails. Flag tests that assert nothing or only the happy path.
11. **Regression.** Run the lane's full suite, `make contracts`, and any other lane's suite the change could touch.
12. **Scope.** Does the diff touch anything outside the lane's owned paths? Does it add a dependency without a note?

## Anti-gaming rules (apply to every role)

- Never delete, skip, `xfail` or weaken a test, widen a tolerance, or add `# noqa` or `pragma: no cover` to get green. If a test is wrong, change it in a separate commit with a one-line justification in the review file, and the reviewer must approve it.
- Never hard-code a fixture's expected output into the implementation.
- Never edit `contracts/`. A suspected contract problem goes in `QUESTIONS.md` under `CONTRACT:` and the task is marked blocked if it cannot proceed.
- Never change another lane's files. If you need a change there, write it in `QUESTIONS.md` under `CROSS-LANE:`.
- Do not mark a task done because `make accept-<lane>` passes if the task's own requirements lack tests.

## Lane review (final)

A fresh reviewer produces `.agent/REVIEW-lane.md`:

1. A **coverage matrix**: every requirement in `requirements.md` to the test and code that satisfy it. Any requirement without both is a blocker.
2. Cross-task regressions: run everything, including the other lanes' suites on the rebased branch.
3. The lane's `make accept-<lane>` finalized per the spec's acceptance task and passing from a clean checkout.
4. Docs: `docs/lanes/<lane>.md` written; README and spec updated where behavior differs.
5. Measured targets (latency, accuracy, size) recorded with the command that produced them.
Fix and re-review until it approves or three rounds pass.

## Merge protocol (human controlled)

1. `python scripts/lanes.py gate <lane>` in a clean, rebased worktree: contracts, foundation and the lane's accept target must pass.
2. Merge to `main` with a squash or merge commit named `lane(<name>): <summary>`.
3. Everyone else runs `python scripts/lanes.py sync`.
4. Merge order: generator, stats, verifier, overlay, evals, agents, web (with api), azure, integration. Earlier lanes are the ones others stub against, so merging them first removes stubs sooner.

## Conflict hotspots and how they are avoided

- Each lane owns its directory and its own `make/lane-<name>.mk`; the root `Makefile` only includes `make/*.mk`.
- Each Python service has its own `pyproject.toml`. Nobody edits the root `pyproject.toml` or `setup.cfg`.
- `docs/` files are per lane. `docs/BUILD_PLAN.md` is edited by the human only.
- Shared library changes (`services/common`) are a **cross-lane request**: write it in `QUESTIONS.md`; the human (or the foundation agent) applies it on `main`; lanes sync.

## Time boxes

A task running over 90 minutes of wall time, or a lane that has not reached its fixture-level acceptance by gate G1 in `agents/SCHEDULE.md`, is escalated rather than extended. The cut order in `docs/BUILD_PLAN.md` still applies.
