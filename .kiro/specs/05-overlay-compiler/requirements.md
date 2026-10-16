# Spec 05: Overlay compiler (Render)

Turns verified claims, snapshots and tracking thresholds into a resolved, timed overlay stream for the renderer.

## User stories
- As a broadcast operator, I want overlays that never collide and never show something unverified.
- As a viewer, I want the density and language I chose.
- As a judge, I want event-to-overlay latency measured and broken down by stage.

## Requirements

### 1. Inputs and outputs
1.1 THE compiler SHALL consume verified claims, snapshots, threshold notices, events and profiles, and SHALL publish overlays on the `overlays` topic and store them.
1.2 EVERY overlay SHALL pass `validate_overlay`, and every stream SHALL pass `check_overlays` with snapshots and profiles supplied.
1.3 THE compiler SHALL produce one overlay stream per active profile, with `lang` and `profile_id` set.

### 2. Kinds and sources
2.1 `lower_third`: for a verified, non-superseded claim with a rendering in the profile's language; `text` copied exactly; `kicker` chosen by claim kind (`causal_explanation` → `why_it_matters`, goal or key shot → `key_moment`, recap-level → `recap`).
2.2 `stat_card`: for verified `metric_value` claims, one to four per card; `value` and `unit` taken from the claim and the registry, never reformatted.
2.3 `momentum_bar`: from the whole-match or rolling snapshot, one index, both teams, window equal to the snapshot window.
2.4 `player_tag`: from tracking threshold notices, with an `indicator` whose `observed` equals the snapshot or frame value and meets its threshold; plain name tags for the focus player.

### 3. Timing
3.1 `trigger_seq` SHALL be the event that caused compilation, and `start_ms` SHALL be at least that event's time plus the measured compile delay.
3.2 THE compiler SHALL drop with reason `stale` any overlay that cannot start within its kind's wait limit.
3.3 `duration_ms` defaults SHALL be configuration per kind (lower third 7 s, stat card 8 s, momentum bar 10 s, player tag 3 s).

### 4. Priority, personalization and density
4.1 `priority` SHALL be round(100 × max salience of cited claims), plus profile boosts (+15 favorite team or player or the focus player, +10 the focus metric), capped at 100.
4.2 FOR overlays with no claims THE priority SHALL come from a per-kind base in configuration.
4.3 THE compiler SHALL apply the profile's density floor (minimal 70, standard 40, rich 0) and SHALL omit overlays below it from that profile's stream, counting them in a metric. The contracts define no drop reason for density, so these are not written as `dropped` records.

### 5. Collision resolution
5.1 THE compiler SHALL keep within the slot capacities (lower third 1, stat card 1, momentum bar 1, player tag 3).
5.2 WHEN a new overlay finds the slots full THEN it SHALL preempt the lowest-priority occupant only if its priority is greater than or equal to that occupant's and the occupant has started, otherwise it SHALL be dropped as `collision`.
5.3 EVERY decision (scheduled, preempted with `displaced_by`, dropped with a reason) SHALL be written to the stream.

### 6. Verified-only gate
6.1 THE compiler SHALL treat a claim as eligible only if `validate.eligible_claims` says so, and SHALL record an overlay as `dropped` with reason `unverified` when asked to show an ineligible claim.
6.2 FOR any run, the count of shown overlays citing an unverified or superseded claim SHALL be zero and SHALL be reported.

### 7. Latency
7.1 EVERY overlay SHALL carry `latency` with `event_emitted_at` copied from the trigger event, `compiled_at`, and `stages_ms` taken from spans.
7.2 THE compiler SHALL expose p50, p95 and max event-to-overlay latency per kind and per tier.

### 8. Determinism
8.1 GIVEN the same inputs and a fixed clock THE compiler SHALL output the same stream.
