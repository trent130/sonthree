# Spec 09: Integration, report and demo

Joins the lanes, proves the claims in the pitch with measured numbers, and produces the submission. Starts when lanes reach their fixture gate and finishes last.

## User stories
- As a judge, I want to open one repo, run one command and see the system work.
- As the presenter, I want a rehearsed two-minute story that cannot fail on camera.
- As a reviewer, I want every number in the pitch to trace to a file in the repo.

## Requirements

### 1. End-to-end run
1.1 WHEN `make demo` runs THEN the system SHALL start all services in local mode, stream the demo match's first 20 minutes at 20x, and serve the web app, with no cloud access and no live model calls (replay cassettes).
1.2 WHEN `make demo-live` runs with cloud configuration THEN the same flow SHALL run against Azure and live models.
1.3 THE end-to-end run SHALL produce, for the whole match, documents on every topic and SHALL finish with a validation pass over every produced document.

### 2. End-to-end invariants (automated)
2.1 EVERY document produced SHALL pass its `validate_*` function, and the full run SHALL pass `validate.py` with all semantic checks (stream, claims, verdicts, overlays, snapshots, profiles, state, recap).
2.2 THE count of shown overlays and recap sections citing an unverified or superseded claim SHALL be zero.
2.3 THE number of dead-lettered documents SHALL be zero.
2.4 TWO runs in replay mode SHALL produce identical documents apart from wall-clock fields.
2.5 THE demo path SHALL pass `validate.py --require-reviewed` (no unreviewed non-English text shown).
2.6 THE fault-injection scenario (judge down for 60 s, one service crash and restart) SHALL end with the invariants 2.1 to 2.3 intact.

### 3. Report
3.1 WHEN `make report` runs THEN it SHALL write `docs/REPORT.md` containing: the unverified-shown count, document counts per topic, event-to-overlay latency (p50, p95, max) per kind and tier with the stage breakdown, the Verifier results from the test split with set and Verifier versions, the data-validation summary, and the fault-injection outcome.
3.2 EVERY figure in the README, the pitch and the video SHALL be copied from `docs/REPORT.md` or the files it links.

### 4. Demo
4.1 THE demo SHALL follow `docs/demo-script.md`, which fits under 2 minutes with the beats in `design.md`.
4.2 THE demo SHALL use a fixed seed, fixed profiles and a fixed injected operator, so every take is identical.
4.3 THE video SHALL contain no third-party trademarks (no club crests or league logos) and no copyrighted music, and SHALL show the project running on the platform it was built for.

### 5. Submission package
5.1 THE repository SHALL be public, newly created for this hackathon, and SHALL contain the code, the contracts, the specs and the docs.
5.2 THE README SHALL contain the elevator pitch (what was built, which Microsoft and Azure technologies are used, what it does, what problem it solves), the five-stage pipeline diagram, setup and run instructions, and the link to the report.
5.3 THE project page SHALL link the repository, the public video URL, and be linked to the challenge; its tagline SHALL match the pitch.
5.4 THE submission SHALL be made at least one day before the deadline of 27 October.
