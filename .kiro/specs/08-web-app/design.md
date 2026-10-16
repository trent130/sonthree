# Design: Web app

## Stack
React + TypeScript + Vite, a small state store (Zustand), canvas for the pitch (SVG for static markings), CSS variables for theming. Types generated from `contracts/schemas` with `json-schema-to-typescript` in a `pnpm gen:types` step; `ajv` 2020 validates in dev.

## Data flow
```
API (FastAPI) ──SSE──▶ app: /stream/overlays?profile=…  /stream/events  /stream/state
              ──REST─▶ /claims/:id  /matches/:id/recap  /profiles  /demo/inject
```
The API reads from the bus and Store and re-publishes over server-sent events. Replay control (play, pause, speed, seek) is a REST call to the generator's stream endpoint; the API relays it. The client keeps a **match clock** (ms) driven by the server's clock events and local interpolation; everything on screen is a pure function of `(clock, documents received)`.

## Components
`PitchCanvas` (frames to positions with interpolation), `OverlayLayer` (renders active overlays per kind and slot), `EvidenceChip` and `ClaimPanel`, `ProfileBar`, `RecapView`, `TransparencyHud`, `LatencyHud`, `DemoControls`. A `useClock` hook and a `selectActiveOverlays(clock)` selector are the core logic and are unit-tested.

## Decisions
- **Render payloads, never recompute.** A bug in client formatting cannot change a number. Number formatting uses the unit only.
- **Slots are visual regions** (lower third bottom, stat card side, momentum bar top, tags on pitch) so collisions are impossible by contract.
- **Profile switching** reuses the server's per-profile streams; the client just resubscribes.
- **Demo mode** is a build flag and a server setting that hides unreviewed non-English text and enables `/demo/inject`.
- **Design:** a restrained broadcast-style look (dark default, high contrast, one accent per team color from metadata). Use the repository's frontend design guidance for typography and spacing rather than template defaults.

## Testing
Unit: selectors, clock, interpolation. Contract: load `contracts/examples/valid/*`, render, assert the expected overlays at known clock values (including the dropped ones not appearing). Component tests for chip to panel. Playwright e2e on the demo match: play 2 minutes at 20x, assert HUD shows zero unverified shown, inject a bad claim and see it rejected, switch language and see the overlay change.
