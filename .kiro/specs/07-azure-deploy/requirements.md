# Spec 07: Azure deployment and operations

Targets the "Best Azure Cloud Native Integration", "Best Enterprise Solution" and "Best Use of Microsoft Foundry" prizes, and gives the demo a hosted URL.

## User stories
- As a judge, I want a running deployment I can open.
- As an enterprise reviewer, I want identity, secrets, audit and deployment handled the way production would.
- As the developer, I want one command to deploy and one to tear down, so cost stays under control.

## Requirements

### 1. Infrastructure as code
1.1 THE repository SHALL provision all resources from Bicep through `azd up`, and remove them with `azd down --purge`.
1.2 THE deployment SHALL create: a Container Apps environment and one container app per service (generator, stats, verifier, agents, overlay, api, web), Azure Event Hubs with one hub per topic, Azure Database for PostgreSQL, Key Vault, Application Insights with a Log Analytics workspace, a container registry, and a Foundry project with the model deployments named in configuration.
1.3 EVERY service SHALL authenticate to Azure resources with a managed identity and `DefaultAzureCredential`; THE deployment SHALL contain no connection strings or keys in app settings.
1.4 THE PostgreSQL role used by services SHALL have INSERT and SELECT only on audit tables (no UPDATE, DELETE or TRUNCATE).

### 2. Event-driven operation
2.1 THE services SHALL consume and publish through Event Hubs with `match_id` as the partition key and consumer groups per service.
2.2 THE container apps SHALL scale on Event Hubs lag where supported and SHALL scale to zero when idle, except the API.
2.3 THE system SHALL switch between local and Azure modes only through configuration (`MODE`).

### 3. Foundry
3.1 THE deployment SHALL expose the model deployments the agents and judge use, and SHALL send traces of agent runs to the Foundry project or Application Insights so a run can be inspected.
3.2 THE eval harness SHALL be able to mirror its results to the Foundry project (best effort, preview feature).

### 4. Observability
4.1 THE deployment SHALL ship a dashboard (workbook) with: documents per topic, rejected and dead-lettered counts, Verifier verdict mix, p50 and p95 event-to-overlay latency per kind and tier, and judge availability.
4.2 THE API SHALL expose `/healthz` and `/metrics` and every service SHALL log structured JSON with `match_id` and document ids.

### 5. CI and CD
5.1 THE CI workflow SHALL run lint, tests, the contract suite, the contracts lock check and bicep `build` and lint, with no secrets.
5.2 THE CD workflow SHALL deploy on a manual trigger or a tag, using federated credentials (OIDC), never stored secrets.
5.3 A deploy SHALL run a smoke test that streams the demo match's first 2 minutes at 20x and asserts that documents appear on every topic and zero invalid documents are rejected.

### 6. Cost and safety
6.1 THE deployment SHALL set a budget alert and SHALL tag every resource with `project=receipts`.
6.2 THE deployment SHALL use the smallest SKUs that pass the smoke test and SHALL document the estimated cost for a day of use.
6.3 THE system SHALL keep a documented fallback: the full demo runs locally with `make demo` and replay cassettes if Azure is unavailable.
