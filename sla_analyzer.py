"""
SLA Analyzer — evaluates cloud metrics against SLA targets.

Produces per-metric compliance stats, an overall SLA score, a
detailed violations table, and auto-generated plain-language insights
suitable for display in the dashboard.
"""

import pandas as pd
import numpy as np
from sla_simulator import DEFAULT_SLA_TARGETS


# ── Metric metadata ─────────────────────────────────────────────────
# Each entry: (column, display_name, unit, comparison, higher_is_better)
METRIC_DEFS = [
    ("uptime_pct",       "Uptime",        "%",  "gte", True),
    ("response_time_ms", "Response Time",  "ms", "lte", False),
    ("error_rate_pct",   "Error Rate",     "%",  "lte", False),
    ("availability_pct", "Availability",   "%",  "gte", True),
]


def evaluate_compliance(
    df: pd.DataFrame,
    targets: dict | None = None,
) -> dict:
    """Return a dict with per-metric compliance info and an overall score.

    Returns
    -------
    {
        "metrics": {
            "<col>": {
                "display_name", "unit", "target", "current_avg",
                "current_latest", "compliance_pct", "compliant",
                "comparison", "higher_is_better",
            },
            ...
        },
        "overall_score": float,   # weighted average of compliance %s
        "overall_compliant": bool,
    }
    """
    targets = targets or DEFAULT_SLA_TARGETS
    results: dict = {}

    for col, display, unit, cmp, hib in METRIC_DEFS:
        target_val = targets[col]
        avg_val = df[col].mean()
        latest_val = df[col].iloc[-1]

        if cmp == "gte":
            compliant_mask = df[col] >= target_val
        else:
            compliant_mask = df[col] <= target_val

        compliance_pct = compliant_mask.mean() * 100

        results[col] = {
            "display_name":    display,
            "unit":            unit,
            "target":          target_val,
            "current_avg":     round(avg_val, 4),
            "current_latest":  round(latest_val, 4),
            "compliance_pct":  round(compliance_pct, 2),
            "compliant":       compliance_pct == 100.0,
            "comparison":      cmp,
            "higher_is_better": hib,
        }

    # Overall score = mean compliance across all four metrics
    scores = [v["compliance_pct"] for v in results.values()]
    overall = round(sum(scores) / len(scores), 2)

    return {
        "metrics": results,
        "overall_score": overall,
        "overall_compliant": all(v["compliant"] for v in results.values()),
    }


def build_violations_table(
    df: pd.DataFrame,
    targets: dict | None = None,
) -> pd.DataFrame:
    """Return a tidy DataFrame listing every individual SLA violation."""
    targets = targets or DEFAULT_SLA_TARGETS
    rows = []

    for col, display, unit, cmp, _ in METRIC_DEFS:
        target_val = targets[col]

        if cmp == "gte":
            mask = df[col] < target_val
        else:
            mask = df[col] > target_val

        violations = df.loc[mask, ["timestamp", col]].copy()
        if violations.empty:
            continue

        violations = violations.rename(columns={col: "actual_value"})
        violations["metric"] = display
        violations["target"] = f"{'≥' if cmp == 'gte' else '≤'} {target_val} {unit}"
        violations["deviation"] = (violations["actual_value"] - target_val).abs().round(4)
        violations["severity"] = violations["deviation"].apply(_severity_label)

        rows.append(violations)

    if not rows:
        return pd.DataFrame(columns=["timestamp", "metric", "actual_value",
                                      "target", "deviation", "severity"])

    result = pd.concat(rows, ignore_index=True)
    result = result.sort_values("timestamp", ascending=False).reset_index(drop=True)
    return result[["timestamp", "metric", "actual_value", "target",
                    "deviation", "severity"]]


def _severity_label(deviation: float) -> str:
    """Classify deviation magnitude into severity buckets."""
    if deviation < 0.05:
        return "Warning"
    elif deviation < 0.5:
        return "Moderate"
    else:
        return "Critical"


# ── Insight generation ───────────────────────────────────────────────

def generate_insights(
    df: pd.DataFrame,
    compliance: dict,
    violations_df: pd.DataFrame,
    targets: dict | None = None,
) -> list[str]:
    """Return 2-4 plain-language observations about the SLA data.

    These are designed to sound like what an SRE would say during a
    status review — short, specific, and actionable.
    """
    targets = targets or DEFAULT_SLA_TARGETS
    insights: list[str] = []

    # ── 1. Worst-performing metric ───────────────────────────────────
    metrics = compliance["metrics"]
    worst_col = min(metrics, key=lambda k: metrics[k]["compliance_pct"])
    worst = metrics[worst_col]
    insights.append(
        f"**{worst['display_name']}** is the weakest metric at "
        f"**{worst['compliance_pct']:.1f}%** compliance "
        f"(target: {'at least' if worst['comparison'] == 'gte' else 'at most'} "
        f"{worst['target']} {worst['unit']})."
    )

    # ── 2. Peak-hour concentration for response time ─────────────────
    if not violations_df.empty and "Response Time" in violations_df["metric"].values:
        rt_violations = violations_df[violations_df["metric"] == "Response Time"].copy()
        rt_violations["hour"] = pd.to_datetime(rt_violations["timestamp"]).dt.hour
        peak_hours = rt_violations[(rt_violations["hour"] >= 9) & (rt_violations["hour"] <= 17)]
        pct_in_peak = len(peak_hours) / len(rt_violations) * 100 if len(rt_violations) > 0 else 0
        if pct_in_peak > 55:
            insights.append(
                f"**{pct_in_peak:.0f}%** of response-time violations occurred during "
                f"business hours (09:00-17:00), suggesting load-related degradation."
            )
        elif pct_in_peak < 30 and len(rt_violations) > 3:
            insights.append(
                "Response-time violations are spread across off-peak hours, "
                "pointing to infrastructure issues rather than traffic spikes."
            )

    # ── 3. Violation clustering — bursts vs. scattered ───────────────
    if len(violations_df) >= 4:
        ts = pd.to_datetime(violations_df["timestamp"]).sort_values()
        gaps = ts.diff().dt.total_seconds().dropna()
        median_gap = gaps.median()
        if median_gap < 600:  # less than 10 minutes between violations
            insights.append(
                "Violations tend to **cluster in bursts** rather than occurring "
                "randomly — investigate correlated failure cascades."
            )
        else:
            insights.append(
                "Violations are **spread across the monitoring window**, "
                "indicating intermittent rather than cascading issues."
            )

    # ── 4. Overall health summary ────────────────────────────────────
    score = compliance["overall_score"]
    total_v = len(violations_df)
    if total_v == 0:
        insights.append(
            "All SLA targets met with **zero violations** — the system is "
            "fully healthy for the monitored period."
        )
    elif score >= 99:
        insights.append(
            f"Overall SLA score of **{score:.1f}%** with only **{total_v}** "
            f"minor violation(s) — within acceptable operating margins."
        )
    elif score >= 95:
        insights.append(
            f"Overall SLA score of **{score:.1f}%** with **{total_v}** "
            f"violation(s) — service is degraded; review before next reporting window."
        )
    else:
        insights.append(
            f"Overall SLA score has dropped to **{score:.1f}%** with "
            f"**{total_v}** violation(s) — immediate attention recommended."
        )

    # ── 5. Error rate spike detection ────────────────────────────────
    if "error_rate_pct" in df.columns and len(df) > 0:
        err_max = df["error_rate_pct"].max()
        err_target = targets["error_rate_pct"]
        if err_max > err_target * 5:
            spike_time = df.loc[df["error_rate_pct"].idxmax(), "timestamp"]
            is_multiday = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() > 86400
            time_str = f"{spike_time:%b %d, %H:%M}" if is_multiday else f"{spike_time:%H:%M}"
            insights.append(
                f"Error rate spiked to **{err_max:.2f}%** "
                f"(~{err_max / err_target:.0f}x the SLA target) at "
                f"**{time_str}** — check deployment logs around that window."
            )

    return insights[:4]  # cap at 4 insights to keep the section concise
