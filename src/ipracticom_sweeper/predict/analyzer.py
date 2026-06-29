"""Time-series analyzer: predict when threshold will be crossed."""
from __future__ import annotations
from dataclasses import dataclass
from .linear import linear_regression, predict_at


@dataclass
class Prediction:
    metric: str
    current_value: float
    predicted_time_hours: float | None  # None if not trending toward threshold
    slope: float
    threshold: float


def predict_crossing(
    values: list[tuple[float, float]],
    threshold: float,
    metric_name: str = "value",
) -> Prediction | None:
    """Given a time-series of (timestamp, value) and a threshold, predict when
    the threshold will be crossed.

    Returns None if data is insufficient or value is already past threshold.
    """
    if len(values) < 2:
        return None

    current_ts, current_val = values[-1]
    if current_val >= threshold:
        return None

    try:
        slope, intercept = linear_regression(values)
    except ValueError:
        return None

    if abs(slope) < 1e-9:
        # Not trending (or numerically zero) — no crossing predicted
        return Prediction(
            metric=metric_name,
            current_value=current_val,
            predicted_time_hours=None,
            slope=slope,
            threshold=threshold,
        )

    # Time (in seconds from now) until y=threshold
    # threshold = slope * t + intercept => t = (threshold - intercept) / slope
    target_ts = (threshold - intercept) / slope
    seconds_until = target_ts - current_ts
    hours_until = seconds_until / 3600

    return Prediction(
        metric=metric_name,
        current_value=current_val,
        predicted_time_hours=hours_until,
        slope=slope,
        threshold=threshold,
    )
