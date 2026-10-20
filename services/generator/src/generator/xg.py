"""Documented receipts-xg-1 shot probability model."""

from __future__ import annotations

import math

MODEL_ID = "receipts-xg-1"


def shot_distance_and_angle(x: float, y: float, goal_x: float) -> tuple[float, float]:
    """Return goal-center distance (m) and visible goal angle (degrees)."""
    dx = abs(goal_x - x)
    center_y = 34.0
    distance = math.hypot(dx, y - center_y)
    left_post_y, right_post_y = 30.34, 37.66
    left_vector = (dx, left_post_y - y)
    right_vector = (dx, right_post_y - y)
    cross = left_vector[0] * right_vector[1] - left_vector[1] * right_vector[0]
    dot = left_vector[0] * right_vector[0] + left_vector[1] * right_vector[1]
    angle = abs(math.degrees(math.atan2(cross, dot)))
    return distance, min(angle, 180.0)


def expected_goals(x: float, y: float, goal_x: float) -> float:
    """Logistic distance/angle model; the constants are receipts-xg-1 v1.

    logit(xG) = -0.10 - 0.17 * distance_m + 0.014 * visible_goal_angle_degrees.
    It is a deliberately compact synthetic baseline, not a fitted real-match model.
    """
    distance, angle = shot_distance_and_angle(x, y, goal_x)
    logit = -0.10 - 0.17 * distance + 0.014 * angle
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit))))