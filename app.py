"""Cloud SLA Monitor — an interactive reliability workspace.

Run with .venv\\Scripts\\python.exe -m streamlit run app.py
"""
import datetime as dt
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from dashboard_data import breach_heatmap, custom_window, error_budget, filter_incidents
from dashboard_theme import appearance_control, restored_controls
from dashboard_ui import (
    METRICS, compliance_panel, format_value, heatmap_figure, hero, icon,
    metric_card, telemetry_figure, traffic_figure, radar_figure, distribution_figure,
    incident_ribbon, comparison_figure,
)
from gcp_metrics import check_gcp_environment, fetch_gcp_metrics
from sla_analyzer import METRIC_DEFS, build_violations_table, evaluate_compliance, generate_insights
from sla_simulator import DEFAULT_SLA_TARGETS, generate_metrics, get_adaptive_interval

st.set_page_config(page_title="Cloud SLA Monitor · Signal", page_icon=":material/monitoring:",
                   layout="wide", initial_sidebar_state="expanded")

if 'appearance_restored' not in st.session_state:
    for key, value in restored_controls(st.query_params.get('controls', '')).items():
        st.session_state[key] = value
    st.session_state.appearance_restored = True

# Resolve colors in the browser's inherited native color-scheme. Python theme
# context can lag behind a menu change and leave custom surfaces in the old mode.
tokens = {
    "surface": "light-dark(#FFFFFF,#050505)",
    "border": "light-dark(#E1E7F2,#292929)",
    "subtle": "light-dark(#F3F5FD,#101010)",
    "track": "light-dark(#EDF0F8,#202020)",
    "accent": "light-dark(#6751CD,#B4A4FF)",
    "good": "light-dark(#08745F,#70E3C7)",
    "good-bg": "light-dark(#E4F6EF,#173D3D)",
    "bad": "light-dark(#B32F4C,#FFADB9)",
    "bad-bg": "light-dark(#FDEBF0,#30101A)",
}
css_vars = ";".join(f"--dash-{name}:{value}" for name, value in tokens.items())
st.html(f"<style>:root{{{css_vars}}}</style>")
st.html(Path(__file__).with_name("dashboard.css"))

TZ = ZoneInfo("Asia/Kolkata")
if "snapshot_end" not in st.session_state:
    st.session_state.snapshot_end = dt.datetime.now(TZ).replace(second=0, microsecond=0)
if "refresh_generation" not in st.session_state:
    st.session_state.refresh_generation = 0


@st.cache_data(ttl=300, max_entries=16, show_spinner=False)
def simulated_data(hours, interval, seed, stress, start, end):
    # SLA controls evaluate this fixed telemetry; they do not move the data.
    return generate_metrics(hours=hours, interval_minutes=interval, seed=seed,
                            demo_mode=stress, start_time=start, end_time=end)


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def live_data(project, hours, interval, start, end, generation):
    return fetch_gcp_metrics(project, hours=hours, interval_minutes=interval,
                             start_time=start, end_time=end)


def panel_title(title, subtitle="", tag=""):
    st.html(f'<div class="panel-title">{escape(title)}'
            f'{f"<span class= pill>{escape(tag)}</span>" if tag else ""}</div>'
            f'<div class="panel-kicker">{escape(subtitle)}</div>')


def plot(fig, key, alt):
    st.plotly_chart(fig, width="stretch", key=key, alt=alt,
                    config={"displaylogo": False, "scrollZoom": False,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                            "toImageButtonOptions": {"format": "png", "scale": 2}})


def diagnostics(insights):
    for i, insight in enumerate(insights, 1):
        # Generated text contains only known metric names and numeric data.
        import re
        text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", escape(insight))
        st.html(f'<div class="diagnostic"><span class="num">{i:02d}</span>{text}</div>')


with st.sidebar:
    st.markdown(f'<div class="brand"><span class="brand-mark">{icon("layers")}</span>'
            '<div><strong>signal<span style="color:#8D77EC">.</span></strong>'
            '<small>CLOUD SLA MONITOR</small></div></div>', unsafe_allow_html=True)
    st.caption("Your reliability workspace")
    st.html('<div class="sidebar-eyebrow">TELEMETRY SOURCE</div>')
    source = st.segmented_control("Data source", ["Simulation", "Live GCP"],
                                  default="Simulation", key="source", label_visibility="collapsed")
    source = source or "Simulation"
    environment = check_gcp_environment()
    project = ""
    if source == "Live GCP":
        project = st.text_input("GCP project ID", value=environment.get("project_id") or "",
                                placeholder="your-project-id", key="gcp_project")
        st.caption("Uses your local Google application credentials.")
    st.html('<div class="sidebar-eyebrow">OBSERVATION WINDOW</div>')
    window = st.selectbox("Monitoring window", ["Last 24 hours", "Last 7 days", "Last 30 days", "Custom dates"],
                           key="window", label_visibility="collapsed")
    now = st.session_state.snapshot_end
    ranges = {"Last 24 hours": 24, "Last 7 days": 168, "Last 30 days": 720}
    start = None
    end = now
    date_error = None
    if window == "Custom dates":
        dates = st.date_input("Date range", value=(now.date() - dt.timedelta(days=6), now.date()),
                              max_value=now.date(), key="dates", help="Up to 60 calendar days, inclusive.")
        try:
            start, end = custom_window(dates, now)
            hours = (end - start).total_seconds() / 3600
        except ValueError as exc:
            date_error = str(exc)
            hours = 24
    else:
        hours = ranges[window]
    interval = get_adaptive_interval(hours)
    st.caption(f"{interval}-minute samples · Asia/Kolkata")
    st.html('<div class="sidebar-eyebrow">SIMULATION LAB</div>')
    stress = st.toggle("Stress test", key="stress", disabled=source == "Live GCP",
                        help="Inject more frequent, stronger anomalies into simulated telemetry.")
    if stress and source == "Simulation":
        st.caption("Stress scenario active · 3× anomaly frequency")
    with st.expander("SLA thresholds", icon=":material/tune:"):
        targets = {
            "uptime_pct": st.slider("Uptime ≥ %", 99.0, 100.0, 99.9, .01, key="target_uptime"),
            "response_time_ms": st.slider("Response time ≤ ms", 50.0, 500.0, 200.0, 10.0, key="target_latency"),
            "error_rate_pct": st.slider("Error rate ≤ %", .01, 1.0, .1, .01, key="target_error"),
            "availability_pct": st.slider("Availability ≥ %", 99.0, 100.0, 99.95, .01, key="target_availability"),
        }
        st.caption("Threshold changes re-evaluate the same samples.")
    with st.expander("Simulation settings", icon=":material/science:"):
        seed = st.number_input("Random seed", 0, 9999, 42, key="seed", disabled=source == "Live GCP")
        st.caption("Use a fixed seed to reproduce a scenario.")
    if st.button("Refresh snapshot", icon=":material/refresh:", width="stretch", key="refresh"):
        st.session_state.snapshot_end = dt.datetime.now(TZ).replace(second=0, microsecond=0)
        st.session_state.refresh_generation += 1
        st.rerun()
    st.html('<div class="sidebar-note">Snapshot-based monitoring · refresh to update.</div>')

appearance_slot = st.empty()
appearance_slot.html('<div class="dashboard-toolbar"><div><span class="toolbar-kicker">SIGNAL / CLOUD OPERATIONS</span>'
                     '<strong>Reliability workspace</strong></div>' + appearance_control(
                         st.session_state, st.query_params.get('appearance', st.context.theme.type)) + '</div>')

if date_error:
    st.info(date_error, icon=":material/date_range:")
    st.stop()

fallback = None
using_live = False
if source == "Live GCP":
    with st.spinner("Reading Google Cloud telemetry…"):
        frame, fallback = live_data(project, hours, interval, start, end, st.session_state.refresh_generation)
    using_live = frame is not None and not frame.empty
else:
    frame = None
if not using_live:
    frame = simulated_data(hours, interval, int(seed), stress if source == "Simulation" else False, start, end)

if using_live:
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(TZ)
    st.caption("Live GCP · availability uses the same uptime-check observations as uptime.")
elif fallback:
    st.warning(f"Simulation fallback — {fallback} Displayed values are simulated.", icon=":material/cloud_off:")

compliance = evaluate_compliance(frame, targets)
violations = build_violations_table(frame, targets)
insights = generate_insights(frame, compliance, violations, targets)
score = compliance["overall_score"]
source_label = "Live GCP" if using_live else ("Simulation fallback" if fallback else "Simulated telemetry")
window_label = window if window != "Custom dates" else f"{start:%d %b} – {end:%d %b %Y}"
st.html(hero(score, len(violations), source_label, window_label, len(frame), interval))

critical = int(violations.severity.eq("Critical").sum())
latest_passes = sum(m["current_latest"] >= m["target"] if m["higher_is_better"]
                    else m["current_latest"] <= m["target"] for m in compliance["metrics"].values())
st.html(f'<div class="summary-strip"><span><i class="status-dot" style="background:{"#12B89C" if latest_passes == 4 else "#EF7187"}"></i>'
        f'<strong>{latest_passes}/4</strong> latest readings in target</span>'
        f'<span><strong>{len(violations):,}</strong> metric violations in window · {critical} critical</span>'
        f'<span>Snapshot <strong>{frame.timestamp.iloc[-1]:%d %b, %H:%M} IST</strong></span></div>')

view = st.segmented_control("Workspace view", ["Overview", "Incidents", "Data & guide"], default="Overview",
                            key="navigation", label_visibility="collapsed")
view = view or "Overview"

if view == "Overview":
    st.markdown('<div class="metric-grid">' + "".join(
        metric_card(col, compliance["metrics"][col], frame[col]) for col in METRICS) + '</div>', unsafe_allow_html=True)
    st.space("small")
    left, right = st.columns([2.1, 1], gap="medium")
    with left:
        with st.container(border=True, key="telemetry"):
            panel_title("Telemetry explorer", "Follow a signal. Hover for detail, drag to zoom, double-click to reset.", "TIME SERIES")
            chosen = st.segmented_control("Metric", list(METRICS) + ['compare'], default="response_time_ms",
                                           format_func=lambda col: 'Compare all' if col == 'compare' else METRICS[col]["short"], key="chart_metric",
                                           label_visibility="collapsed")
            chosen = chosen or "response_time_ms"
            with st.container(horizontal=True, vertical_alignment="center"):
                show_breaches = st.toggle("Breach markers", value=True, key="breach_markers", disabled=chosen == 'compare')
                smooth = st.toggle("Rolling average", key="smooth", disabled=chosen == 'compare')
            if chosen == 'compare':
                plot(comparison_figure(frame, targets), 'telemetry_plot', 'All four metrics over time with independent units and SLA targets')
            else:
                plot(telemetry_figure(frame, chosen, targets[chosen], show_breaches, smooth),
                     "telemetry_plot", f"{METRICS[chosen]['name']} readings and SLA threshold over time")
    with right:
        with st.container(border=True, key="compliance", height="stretch"):
            panel_title("Reliability profile", "Four signals. One view of your weakest link.", "4 SIGNALS")
            profile = st.segmented_control('Profile view', ['Radar', 'Scores'], default='Radar', key='profile_view', label_visibility='collapsed')
            if profile != 'Scores':
                plot(radar_figure(compliance), 'radar_plot', 'Four-axis compliance profile from zero to 100 percent')
            else:
                st.html(compliance_panel(compliance, len(frame)))
            st.caption("Composite score = average of these four sample compliance rates.")

    with st.container(border=True, key='incident_pulse'):
        panel_title('Incident pulse', 'Each tile summarizes consecutive samples. Color shows the maximum simultaneous breaches in that group.', 'FAILURE TIMELINE')
        st.markdown(incident_ribbon(frame, targets), unsafe_allow_html=True)

    left, right = st.columns([1.4, 1], gap="medium")
    with left:
        with st.container(border=True, key="traffic"):
            panel_title("Request traffic", "Request counts per sampling interval.", "WORKLOAD")
            st.html(f'<div class="traffic-stat"><div><strong>{int(frame.request_volume.sum()):,}</strong><small>Total requests</small></div>'
                    f'<div><strong>{frame.request_volume.mean():,.0f}</strong><small>Average / sample</small></div>'
                    f'<div><strong>{frame.request_volume.max():,.0f}</strong><small>Peak / sample</small></div></div>')
            plot(traffic_figure(frame), "traffic_plot", "Request counts per sampled interval")
    with right:
        with st.container(border=True, key="budget", height="stretch"):
            budget = error_budget(frame, targets["availability_pct"], interval)
            burn = budget["burn_rate"]
            burn_text = "∞" if burn == float("inf") else f"{burn:.1f}×"
            panel_title("Availability error budget", "Estimated from time-weighted availability loss.",
                        "EXHAUSTED" if budget["remaining_pct"] == 0 else "WITHIN BUDGET")
            st.html(f'<div class="budget-body"><div class="budget-ring" style="--remaining:{budget["remaining_pct"]*3.6}deg">'
                    f'<div><strong>{budget["remaining_pct"]:.0f}%</strong><small>remaining</small></div></div>'
                    f'<div class="budget-copy"><strong>{burn_text}</strong><small>Window burn rate<br>1× = allowed budget consumed</small></div></div>'
                    f'<div class="budget-facts"><div><strong>{budget["allowed_minutes"]:.2f} min</strong><small>Allowed loss</small></div>'
                    f'<div><strong>{budget["consumed_minutes"]:.2f} min</strong><small>Estimated loss</small></div>'
                    f'<div><strong>{budget["remaining_minutes"]:.2f} min</strong><small>Remaining</small></div></div>')
            st.caption("Estimate over observed intervals only; telemetry gaps are excluded. Not measured outage duration.")
    with st.container(border=True, key="heatmap"):
        panel_title("Breach activity", "Each tile shows the share of metric checks outside target in that hour. Blank = no samples.")
        plot(heatmap_figure(breach_heatmap(frame, targets)), "heatmap_plot", "Hourly breach rate by calendar date")
        st.html('<div class="heat-legend">00–23 hours · IST <span style="margin-left:auto">0%</span>'
                '<i style="background:#C6F7E7"></i><i style="background:#7964FA"></i>'
                '<i style="background:#C54AF1"></i><i style="background:#F4449A"></i>'
                '<i style="background:#FF5C50"></i>100%</div>')
    with st.container(border=True, key='distribution'):
        panel_title('Latency distribution', 'Distribution of sampled interval latency values. Median and P95 summarize these samples.', 'PERFORMANCE SHAPE')
        plot(distribution_figure(frame, targets['response_time_ms']), 'distribution_plot', 'Latency histogram with SLA boundary, median, and 95th percentile')
    with st.container(border=True, key="insights"):
        panel_title("Signal intelligence", "Rule-based observations to guide your next investigation.", "DIAGNOSTICS")
        diagnostics(insights)

elif view == "Incidents":
    st.subheader("Incident workspace")
    st.caption("Investigate individual metric violations across the selected window.")
    with st.container(horizontal=True):
        for severity, label in [("Critical", "Critical"), ("Moderate", "Moderate"), ("Warning", "Warning")]:
            st.metric(label, int(violations.severity.eq(severity).sum()), border=True)
    with st.container(border=True, key="incidents"):
        a, b, c = st.columns([1, 1, 1.5], vertical_alignment="bottom")
        metric_filter = a.selectbox("Metric", ["All metrics"] + [m[1] for m in METRIC_DEFS], key="incident_metric")
        severity_filter = b.selectbox("Severity", ["All severities", "Critical", "Moderate", "Warning"], key="incident_severity")
        search = c.text_input("Search incidents", placeholder="Search a metric, value, or timestamp…", key="incident_search")
        selected = filter_incidents(violations, metric_filter, severity_filter, search)
        st.caption(f"{len(selected):,} of {len(violations):,} violations · newest first")
        if selected.empty:
            st.success("No incidents match these filters." if len(violations) else "All checks passed. No violations in this window.",
                        icon=":material/check_circle:")
        else:
            display = selected.copy()
            units = {name: unit for _, name, unit, _, _ in METRIC_DEFS}
            display["Observed"] = display.apply(lambda row: f'{row.actual_value:.4f} {units[row.metric]}', axis=1)
            display = display.rename(columns={"timestamp": "Timestamp", "metric": "Metric",
                                              "target": "Target", "severity": "Severity"})
            st.dataframe(display[["Timestamp", "Metric", "Observed", "Target", "Severity"]],
                          hide_index=True, width="stretch", height=380,
                          column_config={"Timestamp": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm")},
                          alt="Filtered SLA violations with observed values, targets, and severity")
        st.download_button("Export filtered incidents", selected.to_csv(index=False).encode("utf-8"),
                            "sla-incidents.csv", "text/csv", icon=":material/download:", key="export_incidents")
    with st.container(border=True, key="scorecard"):
        panel_title("Metric scorecard", "Window averages and latest readings are shown separately.")
        rows = []
        for col, m in compliance["metrics"].items():
            rows.append({"Metric": METRICS[col]["name"],
                         "Latest": f'{format_value(m["current_latest"], col)} {m["unit"]}',
                         "Window average": f'{format_value(m["current_avg"], col)} {m["unit"]}',
                         "Target": f'{"≥" if m["higher_is_better"] else "≤"} {m["target"]:g} {m["unit"]}',
                         "Compliance %": m["compliance_pct"],
                         "Window status": "All checks passed" if m["compliant"] else "Violations recorded"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                      column_config={"Compliance %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")},
                      alt="Per-metric compliance, latest readings, averages, and thresholds")
    with st.expander("How severity is classified"):
        st.markdown("Severity uses absolute deviation from the target: **Warning** below 0.05, "
                    "**Moderate** below 0.5, and **Critical** at or above 0.5, in the metric's own unit. "
                    "Compare severity within a metric; milliseconds and percentage points use different scales.")

else:
    st.subheader("Data & guide")
    st.caption(f"{source_label} · {len(frame):,} observations · timestamps in Asia/Kolkata")
    with st.container(border=True, key="raw"):
        st.dataframe(frame, hide_index=True, width="stretch", height=400,
                      column_config={"timestamp": st.column_config.DatetimeColumn("Timestamp (IST)", format="DD MMM YYYY, HH:mm"),
                                     "uptime_pct": st.column_config.NumberColumn("Uptime (%)", format="%.4f"),
                                     "response_time_ms": st.column_config.NumberColumn("Response time (ms)", format="%.2f"),
                                     "error_rate_pct": st.column_config.NumberColumn("Error rate (%)", format="%.4f"),
                                     "availability_pct": st.column_config.NumberColumn("Availability (%)", format="%.4f"),
                                     "request_volume": st.column_config.NumberColumn("Requests / sample", format="%d")},
                      alt="Raw cloud telemetry for the selected monitoring window")
        st.download_button("Download telemetry CSV", frame.to_csv(index=False).encode("utf-8"),
                            "cloud-telemetry.csv", "text/csv", icon=":material/download:", key="export_data")
    with st.expander("Five-step demonstration walkthrough", expanded=True, icon=":material/play_circle:"):
        st.markdown("""
1. **Start with the overview.** Explain latest readings, window compliance, and the composite score.
2. **Explore a signal.** Switch between uptime, latency, errors, and availability; enable the rolling average and zoom into a breach.
3. **Try the simulation lab.** Turn on Stress test and compare the breach count and availability error budget.
4. **Investigate incidents.** Filter by metric or severity and export the resulting incident log.
5. **Evaluate a different target.** Adjust SLA thresholds against the same samples, then compare a longer window or custom dates.
""")
    with st.expander("Metric definitions & methodology", icon=":material/info:"):
        st.markdown("""
- **Uptime / availability:** percentage readings; higher is better. In Live GCP, both derive from uptime checks.
- **Response time:** latency in milliseconds; lower is better.
- **Error rate:** failed HTTP requests as a percentage; lower is better.
- **Composite score:** the unweighted average of the four sample compliance rates. It is distinct from an uptime SLA.
- **Error budget:** estimated availability loss integrated over sampled intervals and compared with the allowed loss.
- **Simulation:** synthetic telemetry with reproducible anomalies, not production measurements.
- **Snapshots:** values update on refresh. Changing thresholds, charts, or incident filters does not resample telemetry.
""")

st.html(f'<div class="footer"><span>signal. <strong>Cloud SLA Monitor</strong> · Reliability in focus</span>'
        f'<span>{escape(source_label)} · {interval} min sampling · Asia/Kolkata</span></div>')

# Render into the top placeholder after all controls, so theme links preserve
# the latest filters, thresholds, chart selections, and telemetry snapshot.
appearance = st.query_params.get('appearance', st.context.theme.type)
appearance_slot.html('<div class="dashboard-toolbar"><div><span class="toolbar-kicker">SIGNAL / CLOUD OPERATIONS</span>'
                     '<strong>Reliability workspace</strong></div>' + appearance_control(st.session_state, appearance) + '</div>')
