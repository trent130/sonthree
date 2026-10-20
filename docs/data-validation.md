# Synthetic generator data validation

**Status:** PASS  
**Generator:** `0.1.0`  
**Evaluation:** 200 deterministic 90-minute seeds; event-only analysis at 1 Hz (tracking omitted from report workload).

The evaluator uses seeded fictional teams and players only. It computes distributions from generated events; no real match or player data is bundled or replayed.

| Metric | Batch mean / coverage | Target | Result |
|---|---:|---:|:---:|
| goals per match | 2.825 | 2.4–3.2 | PASS |
| shots per team per match | 12.908 | 9–15 | PASS |
| mean xG per shot | 0.107 | 0.08–0.12 | PASS |
| pass completion percent | 83.440% | 78–88% | PASS |
| passes per team per match | 592.697 | 350–600 | PASS |
| possession share coverage | 100.000% | 90–100% | PASS |
| fouls per team per match | 9.963 | 8–14 | PASS |
| yellow cards per match | 3.690 | 2–5 | PASS |
| red cards per match | 0.000 | 0–0.15 | PASS |
| top player speed km/h | 35.867 | 30–36 | PASS |

## Target range sources

These are broad synthetic acceptance bands, not a fitted or reproduced league dataset. They are informed by published aggregate summaries and public competition statistics; the generator does not ingest those data.

- UEFA, Champions League technical reports and competition statistics: https://www.uefa.com/uefachampionsleague/news/
- Premier League, official competition statistics: https://www.premierleague.com/stats
- StatsBomb, public football analytics research and xG methodology: https://statsbomb.com/articles/

The xG model is a compact synthetic baseline (`receipts-xg-1`), calibrated against the fictional shot-location distribution. Targets are heuristics from the generator design and are not claims about a particular season.

## Reproduction

Run `python -m generator report --seeds 1-200 --out docs/data-validation.md`. The command exits non-zero and names every out-of-range metric.
