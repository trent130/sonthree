# Technology and conventions

## Stack
- **Python 3.12** for all services, `ruff` + `pytest`. **FastAPI** for HTTP. **Pydantic only for config**; the JSON Schemas in `contracts/schemas` are the source of truth for documents.
- **Microsoft Agent Framework** (`pip install agent-framework`, GA since April 2026) for the agents and workflows. It ships sequential, concurrent, handoff and group-chat orchestration, and a Foundry integration (`agent-framework-foundry`). Pin the exact version in `pyproject.toml` after checking PyPI on the day you start, and confirm import paths against its current docs. Samples use `from agent_framework import Agent`.
- **Microsoft Foundry** for model deployments, tracing and evaluations. SDK: `azure-ai-projects` (v2 line) with `azure-identity`. Cloud evaluation and code-based custom evaluators (a `grade(sample, item)` function returning a 0 to 1 score) are **preview**, so the local harness is the source of truth for every published number and Foundry is a best-effort mirror.
- **Azure Container Apps** for services, **Azure Event Hubs** for streams (partition key = `match_id`), **Azure Database for PostgreSQL** for the store, **Key Vault**, **managed identity**, **Application Insights** via OpenTelemetry. Provision with **Bicep + `azd`**.
- **React + TypeScript + Vite** for the web app. Types generated from the JSON Schemas (`json-schema-to-typescript`), runtime checks with `ajv` (2020 build) in development.
- Model deployment names come from config (`MODEL_ANALYST`, `MODEL_NARRATOR`, `MODEL_JUDGE`, `MODEL_TRANSLATOR`). Use a different, stronger deployment for the judge than for the Narrator to avoid correlated errors. Check what your Foundry project actually offers; do not hard-code model names.

## Rules that apply everywhere
- **Local mode equals cloud mode.** Every service talks to an `EventBus` and a `Store` interface. In-process and in-memory implementations run the whole system with no Azure dependency (tests, CI, and the recording fallback). Azure implementations are swapped in by config only.
- **Append-only audit.** Claims, verdicts, snapshots and overlays are never updated or deleted. The only permitted change to a stored claim is a new revision that appends a rendering.
- **LLM output is untrusted input.** Constrain it with structured output, validate it against the schema, and let code (not the model) set ids, versions, `as_of_seq`, `produced_by`.
- **Cassette LLM client.** `record` mode stores request and response pairs, `replay` mode serves them. CI runs in `replay`. A live run must never be required for a green build.
- **Time.** Match clock is `match_time_ms`; wall clock is UTC ISO-8601 with milliseconds. Latency is always `compiled_at - event_emitted_at`.
- **Secrets.** None in the repo. `DefaultAzureCredential` in cloud, `.env` (git-ignored) locally.
- **Docs are code.** Every lane updates its section of `docs/` in the same change.

## Definition of done for any task
Tests written first or alongside, `ruff` clean, the lane's `make accept-<lane>` passing, and the relevant `contracts/validate.py` check passing on real output, not only on fixtures.
