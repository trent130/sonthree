# Design: Integration and demo

## Orchestration of `make demo`
`scripts/demo.py` starts services as subprocesses in local mode (bus and store in-process via one `api` host), loads cassettes, starts the generator stream at 20x on the 20-minute demo cut, serves the built web app and opens the browser. `scripts/accept_all.py` runs every lane's accept target and then the end-to-end invariants.

## The invariant checker
`scripts/check_run.py` loads the run's Store snapshot (JSONL export of all topics) and calls `validate.validate_all(...)` with every document kind, then computes the zero-unverified count through `check_overlays`' verified gate, checks dead letters, and writes machine-readable results for the report.

## The report generator
`scripts/report.py` joins: run metrics (from `check_run`), latency histograms (from the overlay compiler), `docs/eval-report.md` (spec 06), `docs/data-validation.md` (spec 01) and fault-injection results. Output is one table-heavy `docs/REPORT.md`. Numbers are generated, never typed.

## Fault injection
A test harness that, during a replay run, (1) makes the judge client raise for 60 s, (2) kills and restarts the agents service mid-run. Expected: fast path continues, LLM-dependent claims stay pending then complete after recovery, no duplicate documents, no unverified claim shown.

## Demo beats (target 1:50, hard limit 2:00)
| Time | Beat | What is on screen |
|---|---|---|
| 0:00 to 0:10 | the problem and promise | title card: "Every claim has receipts" |
| 0:10 to 0:35 | live match with overlays | pitch replay at 20x, a stat card and a lower third appear; click an evidence chip, the cited events light up |
| 0:35 to 1:05 | the Verifier earning its keep | click "inject a bad claim" (`perturb_value`), show rejection with the hint, the rewrite, and the verified result; HUD still shows zero unverified shown |
| 1:05 to 1:25 | personalization | switch to the Swahili casual profile with player focus; the same moment retold, in reviewed Swahili |
| 1:25 to 1:45 | the numbers | zero unverified shown, event-to-overlay latency p50 and p95 with stage breakdown, Verifier catch and false-reject rates from the test split, data-validation tick |
| 1:45 to 1:55 | close | architecture diagram with the Azure and Foundry components named |

Record the video last, from the deployed app if it is healthy and otherwise from `make demo`. Capture the narration separately so a second take needs no re-run. Use no crests, league marks or music.

## Submission checklist
Public repo and a clean first commit history; README with pitch and diagram; `docs/REPORT.md`; contracts and specs included; video uploaded as public on a supported platform; project page created, tagline set, repo and video linked; project linked to the challenge; submitted by 26 October.

## Cut order if time runs short (keep the top, cut from the bottom)
Keep: generator, stats engine, Verifier (deterministic layer), Rules Analyst with templates, overlay compiler, web replay with chips and the inject demo, local `make demo`, the report. Cut in this order: French, Foundry eval mirror, workbook dashboard, LLM Recap Editor (assemble recaps by code), Insight Analyst LLM (keep the Rules Analyst), Event Hubs in cloud (run the local bus inside one container app), Azure deploy itself (record locally and say so honestly). The judge-dependent checks come last of the Verifier work.
