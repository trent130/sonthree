# Kiro specs: Receipts build lanes

Ten specs, one per build lane, each in Kiro's format (`requirements.md` in EARS style, `design.md`, `tasks.md` with requirement references). Copy this folder's contents into the repository root next to `contracts/`. Opencode picks up `AGENTS.md`, Kiro picks up `.kiro/steering` and `.kiro/specs`.

**The contract is the interface. The validator is the acceptance test.** Each lane finishes when `make accept-<lane>` passes, and each lane can start today on `contracts/examples/` fixtures without waiting for its upstream.

## Lanes

| # | Spec | Builds | Depends on | Produces (contract) | Accept with |
|---|---|---|---|---|---|
| 00 | foundation | monorepo, bus, store, validating I/O, cassette LLM client, telemetry, CI | contracts | (all, as a library) | `make accept-foundation` |
| 01 | generator | synthetic match, tracking, xG, realism report, streaming, demo seed | 00 | `event` | `validate.py` on 5 seeds, determinism, realism report |
| 02 | stats-engine | snapshots, threshold notices, match state, `recompute` | 00 | `snapshot`, `match-state` | differential test vs `stats_ref`, `--snapshots`, `--state` |
| 03 | verifier | deterministic checks, causal patterns, judge, verdicts | 00, 02 | `verdict` | eval set: 100% deterministic-class catch, 0% clean false-reject |
| 04 | agent-pipeline | Rules and Insight Analysts, Narrator, Translator, Recap Editor, workflow | 00, 02, 03 | `claim`, `recap` | replay run, claims, verdicts, recap, fault-injection invariants |
| 05 | overlay-compiler | four overlay kinds, resolver, priority, latency stamping | 00, 02 | `overlay` | `--overlays` with snapshots and profiles, resolver property tests |
| 06 | eval-harness | mutator, set builder, harness, report | 00, 03 | `eval-label`, `eval-manifest` | `validate.py --eval`, fake-Verifier metrics test |
| 07 | azure-deploy | Bicep, azd, Event Hubs, Postgres, Foundry, observability, CI/CD | 00 | (infrastructure) | `bicep build`, grants test, deployed smoke test |
| 08 | web-app | pitch replay, overlays, evidence chips, profiles, HUDs, demo controls | contracts only | (UI) | unit, component, Playwright on the demo match |
| 09 | demo-integration | e2e run, invariants, report, demo script, submission | all | `docs/REPORT.md` | `make accept` |

Start order: **00 first (tasks 1 to 5 merged before anyone branches)**, then 01, 02, 03, 05, 06, 08 and 07 in parallel, then 04, then 09.

## Who talks to whom
Services never import each other. They exchange only validated documents:

```
generator ─event→ stats ─snapshot→ agents ─claim→ verifier ─verdict→ agents ─claim(verified)→ overlay ─overlay→ api ─SSE→ web
                    └──matchstate→ agents (recap) ─recap→ api                                    ▲
                                                                             profiles ───────────┘
```

## Schedule (today is 15 Oct; submissions close 27 Oct)
| Gate | Date | Meaning |
|---|---|---|
| G0 | 15 Oct | foundation merged (tasks 1 to 5), Azure access confirmed, all lanes branched |
| G1 | 17 Oct | every lane passes its fixture-level acceptance; first end-to-end chain green on `contracts/examples` |
| G2 | 19 Oct | full local `make demo` on the generator's demo match with replay cassettes |
| G3 | 20 Oct | Azure deployment passing its smoke test; Verifier and eval numbers on the dev split |
| G4 | 21 Oct | feature freeze; test-split run; report generated; demo rehearsed |
| Record | 22 Oct | video recorded and uploaded |
| Submit | 23 Oct | repo public, project page complete, submitted (four days of slack) |

## Decisions these specs make that you should confirm
1. **Event Hubs, not Service Bus,** for the ordered, replayable stream; **Container Apps, not AKS.** AKS is named as the scale-up path only.
2. **Causality is pattern-first.** A causal claim verifies only if a registered pattern (forced turnover, turnover to chance, pass to shot) links the events. The model never approves causality. It makes the hardest eval class deterministic and limits the Analyst to causal stories we can prove.
3. **Two analyst tiers.** A code-only Rules Analyst on a fast path with template (including reviewed Swahili) renderings, and an LLM Insight Analyst on the narrative path. This is what makes sub-second overlays possible.
4. **Latency targets:** fast path p95 within 1.5 s, narrative path p95 within 8 s (matching the overlay wait limit).
5. **A deterministic-class Verifier target of 100 percent** catch and 0 percent false-reject on the full eval set, with judge-class targets set only after the first dev run.
6. **Foundry evaluation is a best-effort mirror.** The cloud evaluation feature and code-based evaluators are in preview; the local harness is the source of every published number.
7. **Local mode equals cloud mode,** and the recording can come from `make demo` if Azure misbehaves.

## Open contract questions (none blocks starting)
- **Judge unavailable.** The verdict schema has no "could not decide" outcome, and an invented failure code would be dishonest. The specs resolve this by emitting no verdict and leaving the claim pending (fail closed). If you would rather record abandonment in the audit log, that is a minor schema addition after G1.
- **Density filtering is not a drop reason.** Overlays below a profile's density floor are omitted from that profile's stream and counted in a metric, since the overlay schema has no reason for it.
- **Stream size.** A 90-minute match at 5 Hz is tens of MB. The generator lets you pick 2 Hz for batch runs; `tracking_hz` is carried in metadata.

## Risks to retire first
Model quota and regional availability (spec 07 task 1, today). The Agent Framework workflow API surface (spec 04 task 2 runs a stub through it on day one). Judge accuracy, which is unknown until the dev run (spec 03 task 9). Cold starts when recording (pre-warm script, spec 07 task 6).
