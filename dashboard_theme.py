"""Visible native theme navigation without a second CSS-only appearance state."""
import datetime as dt
from html import escape
import json
import re
from urllib.parse import urlencode

CHOICES = {
    'window': ['Last 24 hours', 'Last 7 days', 'Last 30 days', 'Custom dates'],
    'source': ['Simulation', 'Live GCP'],
    'navigation': ['Overview', 'Incidents', 'Data & guide'],
    'chart_metric': ['uptime_pct', 'response_time_ms', 'error_rate_pct', 'availability_pct', 'compare'],
    'profile_view': ['Radar', 'Scores'],
    'incident_metric': ['All metrics', 'Uptime', 'Response Time', 'Error Rate', 'Availability'],
    'incident_severity': ['All severities', 'Critical', 'Moderate', 'Warning'],
}
NUMBERS = {'seed': (0, 9999), 'target_latency': (50, 500), 'target_uptime': (99, 100),
           'target_error': (.01, 1), 'target_availability': (99, 100)}
FLAGS = ['stress', 'smooth', 'breach_markers']


def restored_controls(raw):
    try:
        values = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(values, dict):
        return {}
    valid = {}
    for key, choices in CHOICES.items():
        if values.get(key) in choices:
            valid[key] = values[key]
    for key, (low, high) in NUMBERS.items():
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
            valid[key] = int(value) if key == 'seed' else float(value)
    for key in FLAGS:
        if isinstance(values.get(key), bool):
            valid[key] = values[key]
    project = values.get('gcp_project')
    if isinstance(project, str) and re.fullmatch(r'[a-zA-Z0-9:_\-.]{0,128}', project):
        valid['gcp_project'] = project
    if isinstance(values.get('incident_search'), str):
        valid['incident_search'] = values['incident_search'][:500]
    try:
        timestamp = dt.datetime.fromisoformat(values.get('snapshot_end', ''))
        if timestamp.tzinfo is not None:
            valid['snapshot_end'] = timestamp
    except (ValueError, TypeError):
        pass
    try:
        dates = tuple(dt.date.fromisoformat(value) for value in values.get('dates', []))
        if len(dates) == 2:
            valid['dates'] = dates
    except (ValueError, TypeError):
        pass
    return valid


def appearance_url(mode, state):
    if mode not in ('light', 'dark'):
        raise ValueError('Unknown appearance')
    keys = set(CHOICES) | set(NUMBERS) | set(FLAGS) | {'snapshot_end', 'dates', 'gcp_project', 'incident_search'}
    controls = {key: state[key] for key in keys if key in state}
    # Native embed_options also works outside embedded mode, preserving toolbar
    # and sidebar. Unlike CSS-only switches this changes canvas tables too.
    return '?' + urlencode({'appearance': mode, 'embed_options': mode + '_theme',
                            'controls': json.dumps(controls, default=str, separators=(',', ':'))})


def appearance_control(state, appearance):
    return '<nav class="appearance-control" aria-label="Appearance"><span>APPEARANCE</span>' + ''.join(
        f'<a target="_self" href="{escape(appearance_url(mode, state), quote=True)}" '
        f'aria-current="{"true" if mode == appearance else "false"}">'
        f'<span aria-hidden="true">{"☀" if mode == "light" else "☾"}</span> {mode.title()}</a>'
        for mode in ('light', 'dark')) + '</nav>'
