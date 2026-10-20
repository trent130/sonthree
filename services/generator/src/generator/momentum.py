"""Bounded, seeded mean-reverting momentum process."""

from __future__ import annotations

import random


class MomentumProcess:
    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._values = {"home": 0.0, "away": 0.0}

    def update(self, team_side: str, action_intensity: float = 0.0) -> float:
        if team_side not in self._values:
            raise ValueError(f"unknown side: {team_side}")
        other = "away" if team_side == "home" else "home"
        value = self._values[team_side]
        value = value * 0.88 + self._rng.uniform(-0.12, 0.12) + min(0.08, action_intensity)
        self._values[team_side] = max(-1.0, min(1.0, value))
        self._values[other] = max(-1.0, min(1.0, self._values[other] * 0.96))
        return self._values[team_side]

    def value(self, team_side: str) -> float:
        return self._values[team_side]