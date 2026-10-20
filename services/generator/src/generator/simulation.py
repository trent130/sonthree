"""Event-driven seeded match simulation and contract-valid tracking emitter."""

from __future__ import annotations

import hashlib
import math
import random
from bisect import bisect_right
from dataclasses import dataclass
from functools import cache
from typing import Any

import fastjsonschema
from validate import REGISTRY, check_event_stream

from . import GENERATOR_NAME, GENERATOR_VERSION
from .momentum import MomentumProcess
from .names import make_player_names, make_team_names
from .xg import MODEL_ID, expected_goals

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0
_POSITIONS = ("GK", "CB", "CB", "FB", "FB", "DM", "CM", "CM", "AM", "W", "ST")
_ROLES = (
    (5, 34), (24, 23), (24, 45), (31, 12), (31, 56), (43, 34),
    (54, 21), (54, 47), (66, 34), (77, 16), (79, 51),
)
_EVENT_SCHEMA_REF = "urn:receipts:schema:v1:event#/$defs/{}"
_EVENT_SCHEMA_NAMES = {
    "match_metadata": "MatchMetadataEvent",
    "period_start": "PeriodStartEvent",
    "period_end": "PeriodEndEvent",
    "pass": "PassEvent",
    "shot": "ShotEvent",
    "tackle": "TackleEvent",
    "possession_change": "PossessionChangeEvent",
    "pressure": "PressureEvent",
    "foul": "FoulEvent",
    "card": "CardEvent",
    "substitution": "SubstitutionEvent",
    "tracking_frame": "TrackingFrameEvent",
}


def _expand_contract_schema(schema: Any, source: dict[str, Any]) -> Any:
    """Inline frozen contract refs so each generated event validates without ref lookups."""
    if isinstance(schema, list):
        return [_expand_contract_schema(item, source) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        reference = schema["$ref"]
        uri, _, pointer = reference.partition("#")
        target_doc = source if not uri else REGISTRY.contents(uri)
        target: Any = target_doc
        if pointer:
            for part in pointer.lstrip("/").split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        expanded = _expand_contract_schema(target, target_doc)
        siblings = {key: value for key, value in schema.items() if key != "$ref"}
        if not siblings:
            return expanded
        return {"allOf": [expanded, _expand_contract_schema(siblings, source)]}
    return {key: _expand_contract_schema(value, source) for key, value in schema.items()}


def _flatten_all_of(schema: Any) -> Any:
    """Flatten the event contract's allOf object composition without weakening constraints."""
    if isinstance(schema, list):
        return [_flatten_all_of(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    schema = {key: _flatten_all_of(value) for key, value in schema.items()}
    parts = schema.pop("allOf", [])
    if not parts:
        return schema
    merged: dict[str, Any] = {}
    for part in (*parts, schema):
        if not isinstance(part, dict):
            return {"allOf": [*parts, schema]}
        for key, value in part.items():
            if key == "properties":
                merged.setdefault(key, {}).update(value)
            elif key == "required":
                merged[key] = list(dict.fromkeys([*merged.get(key, []), *value]))
            elif key == "unevaluatedProperties" and value is False:
                merged["additionalProperties"] = False
            else:
                merged[key] = value
    return merged


@cache
def _event_validator(event_type: str):
    """Compile the frozen contract variant once for fast per-event validation."""
    schema_id, _, pointer = _EVENT_SCHEMA_REF.format(_EVENT_SCHEMA_NAMES[event_type]).partition("#")
    source = REGISTRY.contents(schema_id)
    schema: Any = source
    for part in pointer.lstrip("/").split("/"):
        schema = schema[part.replace("~1", "/").replace("~0", "~")]
    expanded = _flatten_all_of(_expand_contract_schema(schema, source))
    expanded["$schema"] = "http://json-schema.org/draft-07/schema#"
    return fastjsonschema.compile(expanded, use_default=False)


def _rng(seed: int, subsystem: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{subsystem}".encode()).digest()
    return random.Random(int.from_bytes(digest, "big"))


@dataclass(slots=True)
class _Player:
    player_id: str
    team_id: str
    name: str
    shirt_number: int
    position: str
    starter: bool
    side: str
    role_index: int
    phase: float
    amplitude_x: float
    amplitude_y: float
    sprint_start: float
    sprint_direction: int


@dataclass(slots=True)
class _Team:
    team_id: str
    name: str
    short_name: str
    side: str
    color: str
    roster: list[_Player]
    active: list[_Player]
    bench: list[_Player]
    substitutions: int = 0


class MatchGenerator:
    """Build a complete synthetic stream; all randomness is derived from seed."""

    def __init__(self, seed: int, minutes: int = 90, tracking_hz: int = 5) -> None:
        if not 0 <= seed <= 4_294_967_295:
            raise ValueError("seed must be between 0 and 4294967295")
        if not 2 <= minutes <= 90:
            raise ValueError("minutes must be between 2 and 90")
        if not 1 <= tracking_hz <= 25:
            raise ValueError("tracking_hz must be between 1 and 25")
        self.seed = seed
        self.minutes = minutes
        self.hz = tracking_hz
        self._unit = 1000.0 / tracking_hz
        self._team_rng = _rng(seed, "teams")
        self._action_rng = _rng(seed, "actions")
        self._movement_rng = _rng(seed, "movement")
        self._momentum = MomentumProcess(_rng(seed, "momentum"))
        self._teams = self._make_teams()
        self._drafts: list[dict[str, Any]] = []
        self._order = 0
        self._possession_number = 0
        self._match_id = f"synthetic-{seed:010d}"
        self.top_speed_kmh = 0.0
        self._forced_attack_side: str | None = None

    def _make_teams(self) -> dict[str, _Team]:
        names = make_team_names(self._team_rng)
        player_names = make_player_names(self._team_rng, 32)
        teams: dict[str, _Team] = {}
        config = (
            ("home", "t_aurelith", names[0], "AUR", "#3478C8"),
            ("away", "t_brindlefen", names[1], "BRI", "#B66A38"),
        )
        name_index = 0
        for side, team_id, name, short_name, color in config:
            roster: list[_Player] = []
            for index in range(16):
                role_index = index if index < 11 else index - 11
                first_x, first_y = _ROLES[role_index]
                if side == "away":
                    first_x = PITCH_LENGTH - first_x
                roster.append(
                    _Player(
                        player_id=f"p_{(101 if side == 'home' else 201) + index:03d}",
                        team_id=team_id,
                        name=player_names[name_index],
                        shirt_number=index + 1,
                        position=_POSITIONS[role_index],
                        starter=index < 11,
                        side=side,
                        role_index=role_index,
                        phase=self._movement_rng.random() * math.tau,
                        amplitude_x=self._movement_rng.uniform(5.0, 12.0),
                        amplitude_y=self._movement_rng.uniform(3.0, 8.0),
                        sprint_start=self._movement_rng.uniform(0.0, 120.0),
                        sprint_direction=self._movement_rng.choice((-1, 1)),
                    )
                )
                name_index += 1
            teams[side] = _Team(
                team_id, name, short_name, side, color, roster, roster[:11], roster[11:]
            )
        return teams

    def _add(
        self,
        event_type: str,
        tick: int,
        period: int,
        payload: dict[str, Any],
        *,
        team_id: str | None = None,
        player_id: str | None = None,
        possession_id: str | None = None,
        location: tuple[float, float] | None = None,
        assist_key: int | None = None,
    ) -> int:
        self._order += 1
        draft = {
            "type": event_type,
            "tick": tick,
            "time": int(round(tick * self._unit)),
            "period": period,
            "payload": payload,
            "_order": self._order,
            "_assist": assist_key,
        }
        if team_id is not None:
            draft["team_id"] = team_id
        if player_id is not None:
            draft["player_id"] = player_id
        if possession_id is not None:
            draft["possession_id"] = possession_id
        if location is not None:
            draft["location"] = {"x": round(location[0], 3), "y": round(location[1], 3)}
        self._drafts.append(draft)
        return self._order

    def _metadata(self) -> dict[str, Any]:
        return {
            "synthetic": True,
            "competition": "Fictional Continental League",
            "venue": "Aurelith Community Ground",
            "teams": [
                {
                    "team_id": team.team_id,
                    "name": team.name,
                    "short_name": team.short_name,
                    "side": team.side,
                    "primary_color": team.color,
                }
                for team in self._teams.values()
            ],
            "players": [
                {
                    "player_id": player.player_id,
                    "team_id": player.team_id,
                    "name": player.name,
                    "shirt_number": player.shirt_number,
                    "position": player.position,
                    "starter": player.starter,
                }
                for team in self._teams.values()
                for player in team.roster
            ],
            "generator": {
                "name": GENERATOR_NAME,
                "version": GENERATOR_VERSION,
                "seed": self.seed,
            },
            "tracking_hz": self.hz,
            "pitch": {"length_m": 105, "width_m": 68},
        }

    def _kickoff(self, side: str, tick: int, period: int) -> tuple[tuple[float, float], str]:
        team = self._teams[side]
        self._possession_number += 1
        possession_id = f"pos_{self._possession_number:05d}"
        ball = (52.5, 34.0)
        self._add(
            "possession_change",
            tick,
            period,
            {"cause": "kick_off", "previous_team_id": None},
            team_id=team.team_id,
            possession_id=possession_id,
            location=ball,
        )
        return ball, possession_id

    def _direction(self, side: str, period: int) -> int:
        home_positive = period == 1
        positive = home_positive if side == "home" else not home_positive
        return 1 if positive else -1

    def _substitute_due(
        self, tick: int, period: int, sub_plan: list[tuple[int, str]]
    ) -> None:
        while sub_plan and sub_plan[0][0] <= tick:
            sub_tick, side = sub_plan.pop(0)
            team = self._teams[side]
            if team.substitutions >= 3 or not team.bench:
                continue
            candidates = [player for player in team.active if player.position != "GK"]
            player_off = candidates[(team.substitutions * 3 + self.seed) % len(candidates)]
            bench_index = next(
                (index for index, player in enumerate(team.bench) if player.position != "GK"),
                None,
            )
            if bench_index is None:
                continue
            player_on = team.bench.pop(bench_index)
            player_on.position = player_off.position
            player_on.role_index = player_off.role_index
            team.active[team.active.index(player_off)] = player_on
            team.substitutions += 1
            self._add(
                "substitution",
                sub_tick,
                period,
                {"player_off_id": player_off.player_id, "player_on_id": player_on.player_id},
                team_id=team.team_id,
            )

    def _pass_target(self, ball: tuple[float, float], direction: int) -> tuple[float, float]:
        rng = self._action_rng
        dx = rng.uniform(3.0, 16.0) * direction
        dy = rng.uniform(-13.0, 13.0)
        return (max(3.0, min(102.0, ball[0] + dx)), max(2.0, min(66.0, ball[1] + dy)))

    def _shot_location(self, side: str, period: int) -> tuple[float, float]:
        direction = self._direction(side, period)
        if direction > 0:
            x = self._action_rng.uniform(80.0, 100.0)
        else:
            x = self._action_rng.uniform(5.0, 25.0)
        return x, self._action_rng.uniform(23.0, 45.0)

    def _shot(
        self, side: str, period: int, tick: int, possession_id: str, assist_key: int | None
    ) -> int:
        team = self._teams[side]
        opponent = self._teams["away" if side == "home" else "home"]
        direction = self._direction(side, period)
        location = self._shot_location(side, period)
        goal_x = PITCH_LENGTH if direction > 0 else 0.0
        xg = expected_goals(*location, goal_x)
        rng = self._action_rng
        roll = rng.random()
        if roll < xg * 1.05:
            outcome = "goal"
        elif roll < xg * 0.88 + 0.28:
            outcome = "saved"
        elif roll < 0.48:
            outcome = "blocked"
        else:
            outcome = "off_target"
        target_y = max(31.0, min(37.0, 34.0 + rng.gauss(0.0, 2.4)))
        return self._add(
            "shot",
            tick,
            period,
            {
                "outcome": outcome,
                "body_part": "foot" if rng.random() < 0.86 else "head",
                "situation": "counter" if self._momentum.value(side) > 0.55 else "open_play",
                "xg": round(xg, 4),
                "xg_model": MODEL_ID,
                "ball_speed_kmh": round(rng.uniform(72.0, 119.0), 1),
                "target": {"y": round(target_y, 2), "z": round(rng.uniform(0.3, 2.1), 2)},
                "goalkeeper_id": next(p.player_id for p in opponent.roster if p.position == "GK"),
                "assist_event_id": None,
            },
            team_id=team.team_id,
            player_id=rng.choice(team.active[6:]).player_id,
            possession_id=possession_id,
            location=location,
            assist_key=assist_key,
        )

    def _simulate_period(
        self, period: int, start_tick: int, end_tick: int, sub_plan: list[tuple[int, str]]
    ) -> None:
        side = "home" if period == 1 else "away"
        ball, possession_id = self._kickoff(side, start_tick, period)
        tick = start_tick + max(1, round(self.hz * 1.2))
        while tick < end_tick - self.hz:
            if self._forced_attack_side is not None and side != self._forced_attack_side:
                self._forced_attack_side = None
            self._substitute_due(tick, period, sub_plan)
            team = self._teams[side]
            opponent_side = "away" if side == "home" else "home"
            opponent = self._teams[opponent_side]
            direction = self._direction(side, period)
            momentum = self._momentum.update(side)
            action_count = self._action_rng.randint(1, 3)
            last_pass_key: int | None = None
            spell_start = tick
            turned_over = False
            for action_index in range(action_count):
                tick += self._action_rng.randint(max(1, self.hz * 2), max(2, self.hz * 5))
                if tick >= end_tick - self.hz:
                    break
                self._substitute_due(tick, period, sub_plan)
                pressure_draft = None
                pressure = self._action_rng.random() < 0.20
                if pressure:
                    defender = self._action_rng.choice(opponent.active[1:])
                    self._add(
                        "pressure",
                        tick,
                        period,
                        {
                            "target_player_id": self._action_rng.choice(team.active[1:]).player_id,
                            "distance_m": round(self._action_rng.uniform(1.0, 6.5), 1),
                            "duration_ms": self._action_rng.randint(500, 4500),
                            "forced_turnover": False,
                        },
                        team_id=opponent.team_id,
                        player_id=defender.player_id,
                        possession_id=possession_id,
                        location=ball,
                    )
                    pressure_draft = self._drafts[-1]
                shoot_now = action_index >= 1 and self._action_rng.random() < (
                    0.035 + max(0.0, momentum) * 0.012
                ) or (action_index >= 1 and self._forced_attack_side == side)
                if shoot_now:
                    self._forced_attack_side = None
                    self._shot(side, period, tick, possession_id, last_pass_key)
                    shot = self._drafts[-1]
                    ball = (shot["location"]["x"], shot["location"]["y"])
                    self._momentum.update(side, 0.06)
                    self._possession_number += 1
                    next_possession = f"pos_{self._possession_number:05d}"
                    self._add(
                        "possession_change",
                        tick,
                        period,
                        {"cause": "shot", "previous_team_id": team.team_id},
                        team_id=opponent.team_id,
                        possession_id=next_possession,
                        location=ball,
                    )
                    possession_id = next_possession
                    side = opponent_side
                    turned_over = True
                    break

                passer = self._action_rng.choice(team.active[1:])
                receivers = [p for p in team.active if p.player_id != passer.player_id]
                receiver = self._action_rng.choice(receivers)
                target = self._pass_target(ball, direction)
                roll = self._action_rng.random()
                if roll < 0.835:
                    outcome = "complete"
                elif roll < 0.89:
                    outcome = "intercepted"
                elif roll < 0.985:
                    outcome = "incomplete"
                else:
                    outcome = "out_of_play"
                pass_key = self._add(
                    "pass",
                    tick,
                    period,
                    {
                        "receiver_id": receiver.player_id if outcome != "out_of_play" else None,
                        "end_location": {"x": round(target[0], 3), "y": round(target[1], 3)},
                        "outcome": outcome,
                        "height": "ground" if self._action_rng.random() < 0.77 else "low",
                        "body_part": "foot",
                        "set_piece": "none",
                    },
                    team_id=team.team_id,
                    player_id=passer.player_id,
                    possession_id=possession_id,
                    location=ball,
                )
                self._momentum.update(side, 0.012)
                ball = target
                if outcome in {"intercepted", "incomplete", "out_of_play"}:
                    if outcome == "intercepted" and pressure_draft is not None:
                        pressure_draft["payload"]["forced_turnover"] = True
                        self._forced_attack_side = opponent_side
                    cause = {
                        "intercepted": "interception",
                        "incomplete": "incomplete_pass",
                        "out_of_play": "out_of_play",
                    }[outcome]
                    self._possession_number += 1
                    possession_id = f"pos_{self._possession_number:05d}"
                    self._add(
                        "possession_change",
                        tick,
                        period,
                        {"cause": cause, "previous_team_id": team.team_id},
                        team_id=opponent.team_id,
                        possession_id=possession_id,
                        location=ball,
                    )
                    side = opponent_side
                    turned_over = True
                    break
                last_pass_key = pass_key

                if self._action_rng.random() < 0.020:
                    fouler = self._action_rng.choice(opponent.active[1:])
                    victim = self._action_rng.choice(team.active[1:])
                    foul_tick = min(tick + 1, end_tick - 1)
                    self._add(
                        "foul",
                        foul_tick,
                        period,
                        {"fouled_player_id": victim.player_id},
                        team_id=opponent.team_id,
                        player_id=fouler.player_id,
                        possession_id=possession_id,
                        location=ball,
                    )
                    if self._action_rng.random() < 0.18:
                        self._add(
                            "card",
                            foul_tick,
                            period,
                            {"card": "yellow", "reason": "foul"},
                            team_id=opponent.team_id,
                            player_id=fouler.player_id,
                        )

                if action_index == action_count - 1 and self._action_rng.random() < 0.32:
                    defender = self._action_rng.choice(opponent.active[1:])
                    self._add(
                        "tackle",
                        tick + 1,
                        period,
                        {"outcome": "won", "tackled_player_id": receiver.player_id},
                        team_id=opponent.team_id,
                        player_id=defender.player_id,
                        possession_id=possession_id,
                        location=ball,
                    )
                    self._possession_number += 1
                    possession_id = f"pos_{self._possession_number:05d}"
                    self._add(
                        "possession_change",
                        tick + 1,
                        period,
                        {"cause": "tackle", "previous_team_id": team.team_id},
                        team_id=opponent.team_id,
                        possession_id=possession_id,
                        location=ball,
                    )
                    side = opponent_side
                    turned_over = True
                    break
            if not turned_over:
                # Keep a spell bounded if its final scheduled pass was cut short.
                if tick <= spell_start:
                    tick = spell_start + 1
                side = opponent_side
                opponent = self._teams[side]
                self._possession_number += 1
                possession_id = f"pos_{self._possession_number:05d}"
                self._add(
                    "possession_change",
                    min(tick + 1, end_tick - 1),
                    period,
                    {
                        "cause": "loose_ball",
                        "previous_team_id": self._teams[
                            "away" if side == "home" else "home"
                        ].team_id,
                    },
                    team_id=opponent.team_id,
                    possession_id=possession_id,
                    location=ball,
                )
            tick += self._action_rng.randint(max(1, self.hz), max(2, self.hz * 3))

    def _sub_plan(self, first_end: int, final_end: int) -> list[tuple[int, str]]:
        rng = self._action_rng
        plan = []
        for side in ("home", "away"):
            for _ in range(3):
                fraction = rng.uniform(0.66, 0.83)
                tick = first_end + int((final_end - first_end) * fraction)
                plan.append((tick, side))
        return sorted(plan)

    def _player_position(self, player: _Player, tick: int) -> tuple[float, float]:
        seconds = tick / self.hz
        base_x, base_y = _ROLES[player.role_index]
        if player.side == "away":
            base_x = PITCH_LENGTH - base_x
        x = base_x + player.amplitude_x * math.sin(seconds * 0.115 + player.phase)
        y = base_y + player.amplitude_y * math.sin(seconds * 0.137 + player.phase * 0.71)
        sprint_phase = (seconds - player.sprint_start) % 120.0
        if sprint_phase < 2.5:
            sprint_offset = 8.6 * sprint_phase
        elif sprint_phase < 5.0:
            sprint_offset = 8.6 * (5.0 - sprint_phase)
        else:
            sprint_offset = 0.0
        x += player.sprint_direction * sprint_offset
        return max(0.0, min(PITCH_LENGTH, x)), max(0.0, min(PITCH_WIDTH, y))

    def _measure_top_speed(self, all_ticks: int) -> float:
        highest = 0.0
        for team in self._teams.values():
            for player in team.roster[:11]:
                previous = self._player_position(player, 0)
                for tick in range(self.hz, all_ticks + 1, self.hz):
                    current = self._player_position(player, tick)
                    speed = math.dist(previous, current) * 3.6
                    highest = max(highest, speed)
                    previous = current
        return round(highest, 2)

    def _frames(self, all_ticks: int, first_end: int) -> list[dict[str, Any]]:
        points: dict[int, tuple[float, float]] = {}
        for draft in self._drafts:
            if "location" not in draft:
                continue
            tick = draft["tick"]
            position = (draft["location"]["x"], draft["location"]["y"])
            if draft["type"] == "shot":
                points[tick] = position
            elif draft["type"] in {"pass", "tackle", "pressure"}:
                points.setdefault(tick, position)
            elif tick not in points:
                points[tick] = position
        node_ticks = sorted(points)
        if not node_ticks:
            points[0] = (52.5, 34.0)
            node_ticks = [0]
        substitution_drafts = sorted(
            (d for d in self._drafts if d["type"] == "substitution"),
            key=lambda d: (d["tick"], d["_order"]),
        )
        output: list[dict[str, Any]] = []
        previous_players: dict[str, tuple[float, float]] = {}
        previous_ball: tuple[float, float] | None = None
        previous_tick: int | None = None
        sub_cursor = 0
        active = {side: list(team.roster[:11]) for side, team in self._teams.items()}

        for tick in range(all_ticks + 1):
            while (
                sub_cursor < len(substitution_drafts)
                and substitution_drafts[sub_cursor]["tick"] <= tick
            ):
                draft = substitution_drafts[sub_cursor]
                side = "home" if draft["team_id"] == self._teams["home"].team_id else "away"
                team = self._teams[side]
                active[team.side] = [
                    p
                    for p in active[team.side]
                    if p.player_id != draft["payload"]["player_off_id"]
                ]
                incoming = next(
                    p for p in team.roster if p.player_id == draft["payload"]["player_on_id"]
                )
                active[team.side].append(incoming)
                sub_cursor += 1

            right = bisect_right(node_ticks, tick)
            if tick in points:
                ball = points[tick]
            elif right == 0:
                ball = points[node_ticks[0]]
            elif right == len(node_ticks):
                ball = points[node_ticks[-1]]
            else:
                left_tick, right_tick = node_ticks[right - 1], node_ticks[right]
                fraction = (tick - left_tick) / (right_tick - left_tick)
                left, right_point = points[left_tick], points[right_tick]
                ball = (
                    left[0] + (right_point[0] - left[0]) * fraction,
                    left[1] + (right_point[1] - left[1]) * fraction,
                )
            ball = (round(ball[0], 3), round(ball[1], 3))
            delta_seconds = (tick - previous_tick) / self.hz if previous_tick is not None else 0.0
            ball_speed = (
                0.0
                if previous_ball is None or delta_seconds <= 0
                else math.dist(ball, previous_ball) / delta_seconds * 3.6
            )
            ball_speed = min(160.0, round(ball_speed, 2))
            players = []
            current_players: dict[str, tuple[float, float]] = {}
            for side in ("home", "away"):
                for player in active[side]:
                    x, y = self._player_position(player, tick)
                    point = (round(x, 3), round(y, 3))
                    prior = previous_players.get(player.player_id)
                    speed = (
                        0.0
                        if prior is None or delta_seconds <= 0
                        else math.dist(point, prior) / delta_seconds * 3.6
                    )
                    players.append(
                        {
                            "player_id": player.player_id,
                            "x": point[0],
                            "y": point[1],
                            "speed_kmh": round(min(40.0, speed), 2),
                        }
                    )
                    current_players[player.player_id] = point
            output.append(
                {
                    "type": "tracking_frame",
                    "tick": tick,
                    "time": int(round(tick * self._unit)),
                    "period": 1 if tick < first_end else 2,
                    "payload": {
                        "frame_index": len(output),
                        "ball": {"x": ball[0], "y": ball[1], "z": 0.11, "speed_kmh": ball_speed},
                        "players": players,
                    },
                    "_order": -10**12 + tick,
                    "_assist": None,
                }
            )
            previous_players = current_players
            previous_ball = ball
            previous_tick = tick
        return output

    def generate(self, include_tracking: bool = True) -> list[dict[str, Any]]:
        self._add("match_metadata", 0, 0, self._metadata())
        self._add("period_start", 0, 1, {"home_attacking_towards": "+x"})
        total_playing_ticks = self.minutes * 60 * self.hz
        first_half_ticks = total_playing_ticks // 2
        second_half_ticks = total_playing_ticks - first_half_ticks
        first_added = self._action_rng.randint(60 * self.hz, 150 * self.hz)
        second_added = self._action_rng.randint(60 * self.hz, 150 * self.hz)
        first_end = first_half_ticks + first_added
        final_end = first_end + second_half_ticks + second_added
        sub_plan = self._sub_plan(first_end, final_end)
        self._simulate_period(1, 0, first_end, sub_plan)
        self._add(
            "period_end", first_end, 1,
            {"added_time_ms": int(round(first_added * self._unit)), "is_final": False},
        )
        self._add("period_start", first_end, 2, {"home_attacking_towards": "-x"})
        self._simulate_period(2, first_end, final_end, sub_plan)
        self._add(
            "period_end", final_end, 2,
            {"added_time_ms": int(round(second_added * self._unit)), "is_final": True},
        )

        self.top_speed_kmh = self._measure_top_speed(final_end)
        frames = self._frames(final_end, first_end) if include_tracking else []
        def event_order(draft: dict[str, Any]) -> tuple[int, int, int]:
            if draft["type"] == "match_metadata":
                priority = 0
            elif draft["type"] in {"period_start", "period_end"}:
                priority = 1
            elif draft["type"] == "tracking_frame":
                priority = 2
            else:
                priority = 3
            return draft["tick"], priority, draft["_order"]

        drafts = sorted(self._drafts + frames, key=event_order)
        by_order: dict[int, int] = {}
        for seq, draft in enumerate(drafts, 1):
            if draft["type"] != "tracking_frame":
                by_order[draft["_order"]] = seq
        events: list[dict[str, Any]] = []
        for seq, draft in enumerate(drafts, 1):
            payload = dict(draft["payload"])
            if draft["_assist"] is not None:
                payload["assist_event_id"] = f"ev_{by_order[draft['_assist']]:07d}"
            event = {
                "schema_version": "1.0.0",
                "event_id": f"ev_{seq:07d}",
                "match_id": self._match_id,
                "seq": seq,
                "type": draft["type"],
                "period": draft["period"],
                "match_time_ms": draft["time"],
                "payload": payload,
            }
            for field in ("team_id", "player_id", "possession_id", "location"):
                if field in draft:
                    event[field] = draft[field]
            try:
                _event_validator(draft["type"])(event)
            except fastjsonschema.JsonSchemaException as exc:
                raise ValueError(
                    f"generated invalid {draft['type']} at seq {seq}: {exc}"
                ) from exc
            events.append(event)
        stream_errors = check_event_stream(events)
        if stream_errors:
            raise ValueError("generated invalid event stream: " + "; ".join(stream_errors[:8]))
        return events


def generate_match(
    seed: int, minutes: int = 90, tracking_hz: int = 5, *, include_tracking: bool = True
) -> list[dict[str, Any]]:
    """Public deterministic API returning schema and semantic-validated events."""
    return MatchGenerator(seed, minutes, tracking_hz).generate(include_tracking=include_tracking)