# Owned by lane verifier. Edit only from the verifier worktree.
export PYTHONPATH := $(CURDIR)/services/verifier/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: accept-verifier
accept-verifier:
	python -m pytest -q services/verifier
