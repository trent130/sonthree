# Owned by lane overlay. Edit only from the overlay worktree.
export PYTHONPATH := $(CURDIR)/services/overlay/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: accept-overlay
accept-overlay:
	python -m pytest -q services/overlay
