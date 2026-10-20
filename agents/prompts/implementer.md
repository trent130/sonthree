# Implementer prompt (reference)

Use `launch.md.tmpl` rendered per lane (`python scripts/lanes.py prompts`). This file lists the habits behind it so you can tune it.

- **Tests first, per requirement.** Name tests after the requirement (`test_req_3_2_...`) so the reviewer and the lane review can trace them.
- **Small commits.** One commit per task, one per fix round. Never leave the branch red at the end of a turn.
- **Run the whole safety net before asking for review:** lane tests, `ruff`, `make contracts`, and your lane's `accept-<lane>` as far as it exists.
- **Prefer the shared library.** Use `receipts_common` writers and readers, ids and the LLM client. If something is missing there, ask via `CROSS-LANE:`.
- **When blocked, move on.** A blocked task does not block the lane unless later tasks depend on it.
- **Report briefly.** State changes and blockers only.
