# Schedule (replaces the schedule in docs/BUILD_PLAN.md)

Submissions close **27 Oct**. The original plan assumed a start on 15 Oct. Work from **20 Oct** leaves seven days, so scope is cut up front and the gates move. Submit on 26 Oct at the latest.

| Gate | Date | Meaning | If missed |
|---|---|---|---|
| G0 | 20 Oct | generator merged, foundation tests confirmed, lanes scaffolded, worktrees created, Azure access checked | cut Azure to "Bicep plus local demo" |
| G1 | 21 Oct | each lane passes its fixture-level acceptance; first end-to-end chain green on `contracts/examples` | pause the lowest-priority lane |
| G2 | 23 Oct | full local `make demo` on the generator's demo match with replay cassettes | freeze scope, fix only what blocks the demo |
| G3 | 24 Oct | Verifier eval numbers on dev; web app polished enough to record; Azure deploy attempted (smoke test or honest "recorded locally") | drop the deploy, record locally |
| G4 | 25 Oct | feature freeze; test-split run once; `docs/REPORT.md` generated; demo rehearsed | |
| Record | 25 to 26 Oct | video recorded, checked for trademarks and music, uploaded public | |
| Submit | 26 Oct | repo public, project page complete, linked to the challenge, submitted | one day of slack remains |

## Scope decisions to make today (apply the cut order now, not later)

Cut from the plan immediately: French (English and Swahili only), the Foundry evaluation mirror, the Azure workbook dashboard, the LLM Recap Editor (assemble the recap by code), and the cloud Event Hubs path unless Azure access is already confirmed. Keep the Insight Analyst LLM only if the Rules Analyst path is already green at G2.

Keep, in priority order: generator, Verifier (deterministic layer) with eval numbers, Rules Analyst with Swahili templates, overlay compiler, web replay with evidence chips and the inject-a-bad-claim demo, `make demo`, `docs/REPORT.md`, then Azure.
