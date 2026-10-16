# Spec 08: Web app (Render and Personalize, on screen)

The 20 percent of the score called user experience, and the surface the video shows. Balanced frontend and backend is a judged item.

## User stories
- As a viewer, I want a pitch replay with overlays that appear in sync with the match.
- As a skeptical viewer, I want to click a claim and see the events that prove it.
- As a fan, I want to switch persona, favorite team or player, and language.
- As a producer, I want to see that nothing unverified is shown and how fast overlays arrive.

## Requirements

### 1. Replay
1.1 THE app SHALL draw the pitch (105 x 68 m, absolute coordinates) and animate players and ball from `tracking_frame` events in sync with the match clock.
1.2 THE app SHALL provide play, pause, speed (1x, 5x, 20x, 60x) and seek, and SHALL stay in sync with overlays and events after a seek.
1.3 THE app SHALL show the scoreboard, clock and period from the match state.

### 2. Overlays
2.1 THE app SHALL render the four overlay kinds from the overlay stream by `start_ms` and `duration_ms` on the match clock, using only the overlay's payload (text, values, units), never re-deriving content.
2.2 THE app SHALL respect slot capacities by rendering exactly the scheduled and preempted overlays active at the current clock.
2.3 `player_tag` SHALL follow the tagged player's position in the tracking frames and show the indicator when present.
2.4 `momentum_bar` SHALL animate between successive values without implying a single zero-sum quantity.

### 3. Evidence
3.1 EVERY lower third and stat card SHALL show an evidence chip listing its claim ids and event ids.
3.2 WHEN the user clicks a chip THEN the app SHALL open a panel with the claim (assertion in words, evidence list, verdict with its checks, lineage and any rewrites) and SHALL highlight the cited events on the pitch and timeline.
3.3 THE panel SHALL show the verdict, the Verifier version and the recomputed value for numeric claims.

### 4. Personalization
4.1 THE app SHALL let the viewer choose mode (casual, analyst, broadcaster), language (English, Swahili, French), favorite team and player, focus (whole match, one player, one metric) and density, and SHALL apply them by selecting or creating the matching profile.
4.2 WHEN a profile changes THEN the overlay stream SHALL switch without restarting the match.
4.3 THE app SHALL show a visible marker for any rendering whose `human_reviewed` is false when not in demo mode, and SHALL not show unreviewed non-English text in demo mode.

### 5. Recap
5.1 THE app SHALL show the half-time and full-time recap, section by section, each with its evidence chips.

### 6. Transparency HUD
6.1 THE app SHALL show a counter of claims verified, rejected, rewritten and shown, and the number of unverified claims shown (which must read zero).
6.2 THE app SHALL show event-to-overlay latency (p50, p95, last) with the per-stage breakdown, using the overlay `latency` fields plus its own receive time.

### 7. Demo controls
7.1 IN demo mode THE app SHALL offer "inject a bad claim", choosing an operator and a recent verified claim, and SHALL show the Verifier rejection, the rewrite hint, the rewritten claim and its verification.
7.2 THE injected claim SHALL never appear in the shown overlays.

### 8. Quality
8.1 THE app SHALL be responsive, support light and dark themes, be keyboard operable, and meet basic accessibility (contrast, focus states, text alternatives for the pitch).
8.2 THE app SHALL validate incoming documents against the JSON Schemas in development and surface violations in the HUD.
