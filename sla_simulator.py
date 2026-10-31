"""
SLA Simulator — generates realistic cloud metrics for demonstration.

Produces time-series data that is *mostly* compliant with SLA targets but
includes controlled violations so the dashboard always has something
interesting to show.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ── Default SLA targets ──────────────────────────────────────────────
DEFAULT_SLA_TARGETS = {
    "uptime_pct":      99.9,    # ≥ 99.9 %
    "response_time_ms": 200.0,  # ≤ 200 ms
    "error_rate_pct":   0.1,    # ≤ 0.1 %
    "availability_pct": 99.95,  # ≥ 99.95 %
}


def _inject_violations(
    series: pd.Series,
    direction: str,
    threshold: float,
    violation_probability: float = 0.08,
    severity_range: tuple = (1.05, 1.40),
    rng: np.random.Generator | None = None,
) -> pd.Series:
    """Randomly push a small fraction of data points past *threshold*.

    Parameters
    ----------
    direction : "above" | "below"
        Whether a violation means the value goes *above* or *below* the
        threshold.
    severity_range : tuple[float, float]
        How far past the threshold the violation can go, expressed as
        multipliers of the threshold distance from the series mean.
    """
    rng = rng or np.random.default_rng()
    mask = rng.random(len(series)) < violation_probability

    if direction == "above":
        # Push selected points above the threshold
        overshoot = rng.uniform(*severity_range, size=mask.sum())
        series.loc[mask] = threshold * overshoot
    else:
        # Push selected points below the threshold
        undershoot = rng.uniform(1 / severity_range[1], 1 / severity_range[0], size=mask.sum())
        series.loc[mask] = threshold * undershoot

    return series


def get_adaptive_interval(hours: float) -> int:
    """Return recommended sampling interval in minutes for responsive rendering.

    Keeps the total data point count between ~250 and ~1400 points regardless
    of window size, guaranteeing sub-30ms chart rendering and zero memory strain.
    """
    if hours <= 24:
        return 5       # 24h * 12 = 288 points
    elif hours <= 72:  # 3 days
        return 10      # 72 * 6 = 432 points
    elif hours <= 168: # 7 days
        return 15      # 168 * 4 = 672 points
    elif hours <= 720: # 30 days
        return 30      # 720 * 2 = 1440 points
    else:              # > 30 days
        return 60      # 1 point per hour


def generate_metrics(
    hours: float = 24,
    interval_minutes: int | None = None,
    seed: int | None = 42,
    sla_targets: dict | None = None,
    demo_mode: bool = False,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> pd.DataFrame:
    """Return a DataFrame of simulated cloud metrics.

    Parameters
    ----------
    hours : float
        Monitoring window duration in hours (used if start_time/end_time not specified).
    interval_minutes : int | None
        Time resolution per point. If None, automatically selects an adaptive interval.
    seed : int | None
        RNG seed for deterministic evaluation.
    sla_targets : dict | None
        Threshold boundaries dictionary.
    demo_mode : bool
        When True, violation probability and severity are increased so the
        dashboard shows more dramatic breaches — useful for live demos.
    start_time : datetime | None
        Custom range starting timestamp.
    end_time : datetime | None
        Custom range ending timestamp.

    Columns
    -------
    timestamp, uptime_pct, response_time_ms, error_rate_pct,
    availability_pct, request_volume
    """
    rng = np.random.default_rng(seed)
    targets = sla_targets or DEFAULT_SLA_TARGETS

    # Calculate time boundaries
    if start_time is not None and end_time is not None:
        start = start_time
        end = end_time
        hours = (end - start).total_seconds() / 3600.0
    else:
        end = end_time or datetime.now().replace(second=0, microsecond=0)
        start = end - timedelta(hours=hours)

    if hours <= 0:
        raise ValueError("Monitoring window must have a positive duration.")

    if interval_minutes is None:
        interval_minutes = get_adaptive_interval(hours)

    if interval_minutes <= 0:
        raise ValueError("Sampling interval must be positive.")
    # A row represents the interval ending at its timestamp. Spacing must match
    # the advertised sampling resolution rather than interpolate both ends.
    timestamps = pd.date_range(start, end, freq=f"{interval_minutes}min", inclusive="right")
    if len(timestamps) == 0:
        timestamps = pd.DatetimeIndex([end])
    n_points = len(timestamps)

    # Demo mode multipliers: more frequent violations with higher severity
    vp_mult = 3.0 if demo_mode else 1.0   # violation probability multiplier
    sv_boost = 0.3 if demo_mode else 0.0   # added to severity upper bound

    # Multi-day cyclical patterns (hour-of-day + weekend load modulation)
    hour_of_day = timestamps.hour
    day_of_week = timestamps.day_of_week
    weekend_weight = np.where(day_of_week >= 5, 0.85, 1.0)

    # ── Uptime (%) — target >= 99.9 ─────────────────────────────────
    uptime = pd.Series(
        rng.normal(loc=99.97, scale=0.02, size=n_points).clip(99.0, 100.0)
    )
    uptime = _inject_violations(
        uptime, direction="below",
        threshold=targets["uptime_pct"],
        violation_probability=min(0.06 * vp_mult, 0.5), rng=rng,
        severity_range=(1.05, 1.40 + sv_boost),
    )

    # ── Response time (ms) — target <= 200 ──────────────────────────
    # Simulate diurnal business hours pattern modulated by day of week
    diurnal = 20 * np.clip(np.sin(np.pi * (hour_of_day - 6) / 12), 0, 1) * weekend_weight
    response_time = pd.Series(
        rng.normal(loc=120 + diurnal, scale=25, size=n_points).clip(30, 500)
    )
    response_time = _inject_violations(
        response_time, direction="above",
        threshold=targets["response_time_ms"],
        violation_probability=min(0.07 * vp_mult, 0.5),
        severity_range=(1.05, 1.60 + sv_boost), rng=rng,
    )

    # ── Error rate (%) — target <= 0.1 ──────────────────────────────
    error_rate = pd.Series(
        rng.exponential(scale=0.03, size=n_points).clip(0, 5)
    )
    error_rate = _inject_violations(
        error_rate, direction="above",
        threshold=targets["error_rate_pct"],
        violation_probability=min(0.08 * vp_mult, 0.5),
        severity_range=(1.2, 3.0 + sv_boost), rng=rng,
    )

    # ── Availability (%) — target >= 99.95 ──────────────────────────
    availability = pd.Series(
        rng.normal(loc=99.98, scale=0.01, size=n_points).clip(99.0, 100.0)
    )
    availability = _inject_violations(
        availability, direction="below",
        threshold=targets["availability_pct"],
        violation_probability=min(0.05 * vp_mult, 0.5), rng=rng,
        severity_range=(1.05, 1.40 + sv_boost),
    )

    # ── Request volume (informational, no SLA) ──────────────────────
    traffic_shape = (500 + 400 * np.clip(np.sin(np.pi * (hour_of_day - 4) / 12), 0, 1)) * weekend_weight
    request_volume = pd.Series(
        rng.poisson(lam=np.maximum(10, traffic_shape.astype(int)), size=n_points)
    )

    df = pd.DataFrame({
        "timestamp":        timestamps,
        "uptime_pct":       uptime.round(4),
        "response_time_ms": response_time.round(2),
        "error_rate_pct":   error_rate.round(4),
        "availability_pct": availability.round(4),
        "request_volume":   request_volume.astype(int),
    })

    return df
