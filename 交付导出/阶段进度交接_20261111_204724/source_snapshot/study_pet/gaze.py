"""Continuous eye direction in character coordinates, including outside the window."""
import math

EYE_MID_X = 306.75 * 280 / 736
EYE_MID_Y = 365.75 * 300 / 800


def gaze_direction(x: float, y: float) -> tuple[float, float]:
    dx = (x - EYE_MID_X) / 110.0
    dy = (y - EYE_MID_Y) / 145.0
    # A soft radial limit keeps changing below the face instead of clipping each
    # coordinate to a fixed maximum partway through the widget.
    divisor = 1.0 + math.hypot(dx, dy)
    return dx / divisor, dy / divisor


def smooth_gaze(current, target, elapsed):
    amount = -math.expm1(-max(0.0, min(elapsed, 0.25)) / 0.075)
    return tuple(a + (b-a)*amount for a, b in zip(current, target))
