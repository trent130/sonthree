# Product: Receipts

**One line:** an AI match-intelligence engine for the Microsoft x Premier League "Inside the Game" hackathon where every claim, overlay and translation carries its evidence and a measured faithfulness score.

**Audience:** studio and streaming teams who need to trust automated football commentary, and fans who want it personalized (mode, favorite club or player, focus, language including Swahili).

**Data:** synthetic, football-realistic only. The generator is a deliverable, not scaffolding.

## The five-stage pipeline (named this way everywhere: code, README, video)

| Stage | Responsibility | Contract out |
|---|---|---|
| Ingest | synthetic events and tracking frames stream in | `event` |
| Interpret | deterministic stats engine plus Analyst agent | `snapshot`, `claim` |
| Explain | Narrator writes why it matters; Verifier proves it | `claim`, `verdict` |
| Render | overlay compiler resolves a timed, collision-aware timeline | `overlay` |
| Personalize | profiles, language, density; recap | `profile`, `match-state`, `recap` |

## What must be true at the end (the pitch)

1. **Zero unverified claims reach the screen.** Measured, not asserted.
2. **Published Verifier numbers** (catch rate, false-reject rate, attribution, rewrite success) from the held-out test split, reproducible from the repo.
3. **Event-to-overlay latency** measured and shown, with a per-stage breakdown.
4. **Native-quality Swahili,** human reviewed before it appears in the demo.
5. **Validated synthetic data:** a report comparing the generator's distributions with published aggregate football ranges.
6. **Enterprise posture:** managed identity, Key Vault, audit log from claim to evidence, infrastructure as code, CI gates.

## Judging map (each criterion is 20%)

| Criterion | Where we earn it |
|---|---|
| Technological implementation | contracts + validator, tests, IaC, CI, documented code |
| Agentic design and innovation | Analyst / Narrator / Verifier / Recap Editor with typed handoffs, rewrite loop, causal patterns |
| Real-world impact | studio overlay format, verified-only policy, personalization, accessibility of language |
| UX and presentation | pitch replay with overlays, evidence chips, persona and language switch, latency HUD, 2-minute video |
| Category adherence | the five-stage pipeline, stated by name |

Prize lanes targeted: Multi-Agent Orchestration (primary), Enterprise, Foundry, Azure Cloud Native.

## Out of scope

Video auto-eventing, audio and speech output, real data, own goals, VAR, shootouts, offsides.
