# Owned by lane agents. Edit only from the agents worktree.
export PYTHONPATH := $(CURDIR)/services/agents/src$(if $(PYTHONPATH),:$(PYTHONPATH))

.PHONY: accept-agents
accept-agents:
	python -m pytest -q services/agents
