# Repository structure and ownership

```
AGENTS.md                   rules for coding agents
.kiro/steering, .kiro/specs this folder
contracts/                  FROZEN. schemas/, validate.py, stats_ref.py, STATS.md, examples/, tests
services/
  common/                   spec 00: config, EventBus, Store, LLM client, telemetry, validating writers
  generator/                spec 01
  stats/                    spec 02
  verifier/                 spec 03
  agents/                   spec 04 (analyst, narrator, translator, recap editor, workflow)
  overlay/                  spec 05
  evals/                    spec 06 (mutator, set builder, harness, report)
  api/                      spec 08/09 (FastAPI: replay control, SSE, demo endpoints)
apps/web/                   spec 08
infra/                      spec 07 (Bicep, azd)
docs/                       architecture.md, data-validation.md, eval-report.md, demo-script.md, contract-issues.md
Makefile  pyproject.toml  .github/workflows/
```

## Import and dependency rules
- Services import `contracts` modules (`validate`, `stats_ref`) and `services.common`. **Services never import each other.** They communicate only through documents on the `EventBus` or the `Store`. That is what lets lanes be built in parallel.
- A service reads upstream documents only through validating readers from `services.common`.

## Lane dependency graph
```
00 foundation ──┬─▶ 01 generator ──▶ 02 stats ──┬─▶ 03 verifier ──▶ 04 agents ──▶ 05 overlay ──▶ 08 web
                │                               └──────────────────────────────▶ 06 evals (needs 03)
                └─▶ 07 azure deploy (independent until 09)                                  09 integration (needs all)
```
Every lane can start on day one against `contracts/examples/` fixtures.

## Naming
Python modules `snake_case`, CLI entry points `python -m <service> <command>`. Document ids follow the contract patterns (`ev_`, `cl_`, `vd_`, `snap_`, `ov_`, `lb_`, `rc_`, `prof_`). Branches `lane/<nn>-<name>`.
