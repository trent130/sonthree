# Spec 00: Foundation (repo, shared library, CI)

The shared base every other lane builds on. It is on the critical path for day one: finish tasks 1 to 5 first and merge before other lanes branch.

## User stories
- As a lane developer, I want a ready monorepo with the contracts installed, so I can start on fixtures immediately.
- As the demo operator, I want the whole system to run with no cloud access, so a flaky network can never ruin the recording.
- As a reviewer, I want every stored or emitted document validated, so invalid data cannot hide.

## Requirements

### 1. Repository and contracts
1.1 WHEN a developer runs `make setup` THEN the system SHALL create the environment and install all services and `contracts` as editable packages.
1.2 WHEN `make contracts` runs THEN the system SHALL run the contract suite in `contracts/` and fail on any failure.
1.3 WHEN any file under `contracts/` differs from the pinned checksum in `contracts.lock` THEN CI SHALL fail, so frozen contracts cannot drift.
1.4 WHEN a service imports `validate` or `stats_ref` THEN the import SHALL resolve with no path hacks.

### 2. EventBus
2.1 THE EventBus SHALL expose `publish(topic, key, doc)` and `subscribe(topic, group, from_offset)` for the topics `events`, `snapshots`, `claims`, `verdicts`, `overlays`, `matchstate`, `recaps`.
2.2 WHEN documents with the same `key` (the `match_id`) are published THEN subscribers SHALL receive them in publish order.
2.3 THE EventBus SHALL have an in-process implementation and an Azure Event Hubs implementation selected only by configuration, with identical behavior in the shared conformance tests.
2.4 WHEN a subscriber restarts THEN it SHALL resume from its last committed offset without losing or reordering documents.

### 3. Store
3.1 THE Store SHALL persist events, snapshots, claims (with revisions), verdicts, overlays, match states, recaps and profiles, with in-memory and PostgreSQL implementations selected by configuration.
3.2 THE Store SHALL be append-only: it SHALL expose no update or delete for stored documents, and the PostgreSQL role used by services SHALL have no UPDATE or DELETE grant on those tables.
3.3 WHEN a claim revision is written THEN the Store SHALL accept it only if it differs from the previous revision in `renderings` alone, and only by adding renderings.
3.4 THE Store SHALL expose `latest_verdict(claim_id)` and `eligible_claims(match_id, as_of_seq)` using the exact rules in `validate.eligible_claims`.

### 4. Validating I/O
4.1 WHEN any service writes a document to the bus or Store THEN the writer SHALL validate it with the matching `validate_*` function and reject invalid documents with an error naming the field.
4.2 WHEN a service reads a document THEN the reader SHALL validate it and route invalid documents to a dead-letter record rather than processing them.
4.3 THE system SHALL count and expose rejected and dead-lettered documents per topic.

### 5. LLM client
5.1 THE LLM client SHALL expose `complete_json(role, schema, messages)` returning parsed, schema-valid output or raising a typed error.
5.2 THE LLM client SHALL support `live`, `record` and `replay` modes; in `replay` it SHALL answer from stored cassettes and fail the test if a request has no cassette.
5.3 WHEN a call exceeds its timeout or fails THEN the client SHALL retry with backoff up to a configured limit, then raise, and SHALL record the attempt count and latency.

### 6. Telemetry
6.1 THE system SHALL emit an OpenTelemetry span per pipeline stage (`interpret`, `explain`, `verify`, `render`) with `match_id`, `claim_id` or `overlay_id`, and duration.
6.2 WHEN an overlay is compiled THEN its `latency.stages_ms` SHALL be derived from those spans, not estimated.

### 7. CI
7.1 WHEN a pull request is opened THEN CI SHALL run lint, unit tests, the contract suite, and every lane's `make accept-<lane>` that has changed.
7.2 THE CI pipeline SHALL run with no network access to Azure and no secrets, using `replay` LLM mode.
