"""Pure calculations shared by the dashboard and its regression tests."""

import datetime as dt

import pandas as pd

from sla_analyzer import METRIC_DEFS


def custom_window(dates, now):
    """Resolve an inclusive date selection without inventing future telemetry."""
    if not isinstance(dates, (list, tuple)) or len(dates) != 2:
        raise ValueError("Choose both a start date and an end date.")
    first, last = dates
    if first > last or last > now.date():
        raise ValueError("Choose an ordered date range ending today or earlier.")
    if (last - first).days >= 60:
        raise ValueError("Choose a window of 60 days or less.")
    start = dt.datetime.combine(first, dt.time.min, tzinfo=now.tzinfo)
    end = min(dt.datetime.combine(last + dt.timedelta(days=1), dt.time.min,
                                 tzinfo=now.tzinfo), now)
    if start >= end:
        raise ValueError("The selected window does not contain any elapsed time.")
    return start, end


def error_budget(frame, availability_target, interval_minutes):
    """Integrate availability loss over sampled intervals (an estimate)."""
    timestamps = pd.to_datetime(frame['timestamp'])
    # Missing telemetry is unknown coverage, not downtime to extrapolate.
    weights = timestamps.diff().dt.total_seconds().div(60).fillna(interval_minutes).clip(0, interval_minutes)
    observed_minutes = float(weights.sum())
    allowed = observed_minutes * (1.0 - availability_target / 100.0)
    consumed = float(((100.0 - frame['availability_pct'].clip(0, 100)) / 100.0 * weights).sum())
    burn = consumed / allowed if allowed > 0 else (float('inf') if consumed > 0 else 0.0)
    return dict(allowed_minutes=allowed, consumed_minutes=consumed,
                remaining_minutes=max(0.0, allowed - consumed),
                remaining_pct=max(0, 100 * (1 - burn)), burn_rate=burn,
                observed_minutes=observed_minutes)


def breach_heatmap(frame, targets):
    """Percent of metric checks that failed per calendar day/hour; gaps are NaN."""
    failed = pd.DataFrame({col: frame[col].lt(targets[col]) if cmp == 'gte'
                           else frame[col].gt(targets[col])
                           for col, _, _, cmp, _ in METRIC_DEFS})
    hourly = failed.mean(axis=1).mul(100).groupby(
        pd.to_datetime(frame['timestamp']).dt.floor('h')).mean()
    table = pd.DataFrame({'value': hourly.values, 'day': hourly.index.strftime('%b %d'),
                          'hour': hourly.index.hour})
    days = list(dict.fromkeys(table['day']))
    return table.pivot(index='day', columns='hour', values='value').reindex(
        index=days, columns=range(24)).astype(float)


def filter_incidents(frame, metric='All metrics', severity='All severities', search=''):
    result = frame
    if metric != 'All metrics':
        result = result.loc[result['metric'].eq(metric)]
    if severity != 'All severities':
        result = result.loc[result['severity'].eq(severity)]
    if search.strip():
        mask = result.astype(str).apply(lambda col: col.str.contains(search.strip(), case=False, regex=False)).any(axis=1)
        result = result.loc[mask]
    return result
