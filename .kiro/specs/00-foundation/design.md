# Design: Foundation

## Layout
`services/common` is one installable package, `receipts_common`:

```
receipts_common/
  config.py        Pydantic settings: MODE=local|azure, model deployment names, endpoints
  bus/             base.py (Protocol), local.py (asyncio queues + offset log), eventhubs.py
  store/           base.py, memory.py, postgres.py, migrations/*.sql
  io.py            ValidatingWriter / ValidatingReader (wraps contracts.validate)
  llm/             client.py, live.py (Agent Framework / Foundry chat client), cassette.py
  telemetry.py     tracer setup, stage_span() context manager, exporter selection
  ids.py           deterministic id allocators: ev_, cl_, vd_, snap_, ov_, rc_
```

## Key decisions
- **Interfaces are Protocols, implementations are swappable.** Tests run the same suite against each implementation (`conformance/`), so "local equals cloud" is tested rather than assumed.
- **The local bus is a durable-in-memory log** (list per topic and key with offsets), so replay, restart and consumer groups behave like Event Hubs.
- **Postgres schema:** one table per document kind, `(match_id, id)` primary key, `doc jsonb not null`, a generated `seq` column where relevant, and indexes on `(match_id, as_of_seq)` and `claim_id`. `claim_revisions(claim_id, revision, doc)` holds renderings changes. Row-level rules come from grants, not application convention.
- **Id allocation** is per match and monotonic, taken inside a transaction (Postgres) or a lock (memory), so ids are stable across replays.
- **Cassette key** = sha256 of `(role, model, schema_name, canonical messages JSON)`; cassettes are stored as JSONL under `tests/cassettes/<lane>/`.
- **Dead letters** are a topic `deadletter` carrying the offending document, the topic it was bound for and the validation errors.
- **Contracts lock:** `contracts.lock` lists sha256 of every file in `contracts/`; `make contracts-lock-check` recomputes and compares.

## Error handling
Validation failures raise `ContractViolation(topic, path, errors)`. Transport failures retry with exponential backoff and jitter, three attempts, then surface to the caller. No component swallows a `ContractViolation`.

## Testing
Conformance tests for bus and store (ordering, resume, append-only, revision rule). Property test: any document from `contracts/examples` round-trips through writer, store and reader unchanged. Cassette tests: record then replay yields identical output; a missing cassette fails loudly.
