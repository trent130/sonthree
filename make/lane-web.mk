# Owned by lane web. Edit only from the web worktree.
export PYTHONPATH := $(CURDIR)/services/api/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: accept-web
accept-web:
	python -m pytest -q services/api
	cd apps/web && pnpm test
