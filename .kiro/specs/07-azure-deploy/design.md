# Design: Azure deployment

## Topology
```
            ┌────────────── Container Apps environment ───────────────┐
 web ◀─SSE─ api ◀──────────────────────────────────────────────────┐   │
            │  generator ─▶ [events hub] ─▶ stats ─▶ [snapshots]     │   │
            │                      │                    │            │   │
            │                      └─▶ agents ◀─────────┘            │   │
            │                          │  ▲ verifier ─▶ [verdicts]   │   │
            │                          ▼  │                          │   │
            │                       [claims] ─▶ overlay ─▶ [overlays]─┘   │
            └──────────────────────────────────────────────────────────────┘
   PostgreSQL (audit store)   Key Vault   App Insights   Foundry project (models, traces, evals)
```
Hubs: `events`, `snapshots`, `claims`, `verdicts`, `overlays`, `matchstate`, `recaps`, `deadletter`.

## Decisions
- **Container Apps over AKS.** Faster to stand up solo and sufficient for the event-driven story. Mention AKS as the scale-up path in the README rather than building it.
- **Event Hubs over Service Bus** for the ordered, replayable match stream. Partition key = `match_id`.
- **Managed identity everywhere**, with role assignments in Bicep: Event Hubs data sender and receiver, Key Vault secrets user, Foundry user, Postgres Entra authentication for the services, container registry pull.
- **One Bicep module per concern** (`network`, `data`, `messaging`, `ai`, `apps`, `monitoring`) composed by `main.bicep`; parameters in `main.parameters.json`; `azure.yaml` for `azd` with one service entry per container.
- **Postgres grants** applied by a post-deploy script: a migration role creates tables, the service role gets INSERT and SELECT only.
- **Models:** deployment names are parameters. Verify availability and quota in the chosen region early (it can take time to get access); do not assume a model is available.
- **Tracing:** OpenTelemetry through the Azure Monitor exporter. Agent Framework telemetry and our stage spans share a trace id per claim lineage.
- **Dashboard:** an Azure Workbook JSON committed under `infra/monitoring/`, built on custom metrics from `/metrics` and traces.
- **Smoke test** runs inside CD against the deployed API, using the demo seed's 2-minute cut at 20x.

## Costs
Use consumption-based container apps with scale-to-zero, the lowest Event Hubs tier that supports the hubs needed, the smallest burstable Postgres SKU, and pay-as-you-go model usage. Add a daily budget alert. Estimate the cost per demo-hour in `docs/architecture.md`.

## Security notes for the README
Identities and roles, no secrets in config, append-only grants, schema validation on every write, audit chain from overlay to claim to evidence to event, dependency pinning, no real data.

## Risks
Model quota and regional availability; Foundry features in preview; Event Hubs tier limits; cold starts on scale-to-zero (keep the API warm, pre-warm before recording).
