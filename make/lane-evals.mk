# Owned by lane evals. Edit only from the evals worktree.
export PYTHONPATH := $(CURDIR)/services/evals/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: accept-evals
accept-evals:
	python -m pytest -q services/evals
