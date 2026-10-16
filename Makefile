# Receipts: starter Makefile. Lanes replace the TODO bodies as they land. Spec 00 task 1 owns this file.
PY ?= python
LANES := foundation generator stats verifier agents overlay evals azure web

.PHONY: setup contracts contracts-lock-check accept $(addprefix accept-,$(LANES)) demo demo-live report

setup:
	$(PY) -m pip install -e contracts -e services/common
	@echo "TODO: install each service and apps/web (pnpm install)"

contracts:
	cd contracts && $(PY) -m pytest -q -p no:cacheprovider

contracts-lock-check:
	$(PY) scripts/contracts_lock.py --check

accept: contracts contracts-lock-check $(addprefix accept-,$(LANES))

accept-foundation: contracts contracts-lock-check
	$(PY) -m pytest -q services/common

accept-generator:
	$(PY) -m pytest -q services/generator
	$(PY) -m generator generate --seed 7 --minutes 90 --out out/match_7.jsonl
	$(PY) contracts/validate.py out/match_7.jsonl
	$(PY) -m generator report --seeds 1-200 --out docs/data-validation.md

accept-stats:
	$(PY) -m pytest -q services/stats
	$(PY) contracts/validate.py out/match_7.jsonl --snapshots out/snapshots.json --state out/match_state.json

accept-verifier:
	$(PY) -m pytest -q services/verifier
	$(PY) -m verifier eval --manifest contracts/examples/eval/manifest.json

accept-agents:
	$(PY) -m pytest -q services/agents

accept-overlay:
	$(PY) -m pytest -q services/overlay

accept-evals:
	$(PY) -m pytest -q services/evals
	$(PY) contracts/validate.py --eval evals/sets/current/manifest.json

accept-azure:
	az bicep build --file infra/main.bicep --stdout > /dev/null

accept-web:
	cd apps/web && pnpm test && pnpm e2e

demo:
	$(PY) scripts/demo.py --local --minutes 20 --speed 20

demo-live:
	$(PY) scripts/demo.py --cloud

report:
	$(PY) scripts/report.py
