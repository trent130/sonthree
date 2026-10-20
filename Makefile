# Receipts: starter Makefile. Lanes replace the TODO bodies as they land. Spec 00 task 1 owns this file.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,$(if $(wildcard contracts/.venv/bin/python),contracts/.venv/bin/python,python3))
PYTHON := $(abspath $(shell command -v "$(PY)"))
LANES := foundation generator stats verifier agents overlay evals azure web

.PHONY: setup contracts contracts-lock-check lint accept accept-00-foundation accept-01-generator $(addprefix accept-,$(LANES)) demo demo-live report

setup:
	@if [ ! -x .venv/bin/python ]; then $(PYTHON) -m venv .venv; fi
	.venv/bin/python -m pip install -e '.[dev]'
	@echo "Foundation and frozen contract modules installed in editable mode."

contracts:
	cd contracts && $(PYTHON) -m pytest -q -p no:cacheprovider

contracts-lock-check:
	$(PYTHON) scripts/contracts_lock.py --check

lint:
	$(PYTHON) -m ruff check services/common services/generator scripts

accept: contracts contracts-lock-check $(addprefix accept-,$(LANES))

accept-foundation: contracts contracts-lock-check
	$(PYTHON) -m pytest -q services/common

accept-00-foundation: accept-foundation

accept-generator:
	$(PY) -m pytest -q services/generator
	$(PY) -m generator verify-demo --config config/demo.json --cut tests/golden/demo-20min.jsonl --golden tests/golden/demo-20min.sha256
	@for seed in 7 19 42 73 $$( $(PY) -c 'import json; print(json.load(open("config/demo.json"))["seed"])' ); do \
		$(PY) -m generator generate --seed $$seed --minutes 90 --hz 1 --out out/match_$$seed.jsonl || exit $$?; \
		$(PY) contracts/validate.py out/match_$$seed.jsonl || exit $$?; \
	done
	$(PY) -m generator generate --seed 7 --minutes 20 --hz 1 --out out/determinism_a.jsonl
	$(PY) -m generator generate --seed 7 --minutes 20 --hz 1 --out out/determinism_b.jsonl
	cmp out/determinism_a.jsonl out/determinism_b.jsonl
	$(PY) -m generator report --seeds 1-200 --out docs/data-validation.md

accept-01-generator: accept-generator

demo:
	$(PY) scripts/demo.py --local --minutes 20 --speed 20

demo-live:
	$(PY) scripts/demo.py --cloud

report:
	$(PY) scripts/report.py

# Lane-owned targets (one fragment per lane, edited only from that lane's worktree).
-include make/*.mk
