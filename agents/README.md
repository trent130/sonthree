# Agent kit

Parallel lanes in git worktrees, each driven by an implementer agent with a review and fix loop.

```
python scripts/lanes.py scaffold          # on main: per-service stubs and make/lane-*.mk, then commit
python scripts/lanes.py create --setup    # one worktree per lane under ../<repo>-wt/
python scripts/lanes.py prompts           # agents/launch/<lane>.md, one prompt per lane tab
python scripts/lanes.py list              # dashboard: branch, ahead/behind, dirty, agent state
python scripts/lanes.py sync              # rebase clean lane branches onto main
python scripts/lanes.py gate <lane>       # merge gate in the lane worktree
```

Open each worktree folder in its own VS Code window or agent tab and paste the matching `agents/launch/<lane>.md`. The loop, roles, severity rules and merge protocol are in `PROTOCOL.md`. Reviewer prompts are templates (`reviewer.md`, `fixer.md`, `lane-reviewer.md`); fill the `{{...}}` fields or let your agent do it.
