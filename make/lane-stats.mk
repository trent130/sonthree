# Owned by lane stats. Edit only from the stats worktree.
export PYTHONPATH := $(CURDIR)/services/stats/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: accept-stats
accept-stats:
	python -m pytest -q services/stats
