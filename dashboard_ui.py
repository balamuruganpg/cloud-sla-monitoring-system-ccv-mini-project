"""Presentation helpers: metric identity, accessible SVGs, and Plotly figures."""

from html import escape

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

METRICS = {
    'uptime_pct': dict(name='Uptime', short='Uptime', color='#9162FF', icon='pulse', unit='%', decimals=3),
    'response_time_ms': dict(name='Response time', short='Latency', color='#00B8CF', icon='clock', unit='ms', decimals=1),
    'error_rate_pct': dict(name='Error rate', short='Errors', color='#F44076', icon='bolt', unit='%', decimals=4),
    'availability_pct': dict(name='Availability', short='Availability', color='#00BE88', icon='globe', unit='%', decimals=3),
}

PATHS = {
    'pulse': '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'bolt': '<path d="m13 2-8 12h6l-1 8 9-13h-6z"/>',
    'globe': '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
    'layers': '<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
    'arrow': '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    'shield': '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
}


def icon(name):
    return f'<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{PATHS[name]}</svg>'


def format_value(value, col):
    meta = METRICS[col]
    return f"{value:,.{meta['decimals']}f}"


def sparkline(values, color):
    values = np.asarray(values, dtype=float)
    # Bucket means preserve the whole window and avoid enormous SVG payloads.
    values = np.array([part.mean() for part in np.array_split(values, min(48, len(values)))])
    span = np.ptp(values)
    y = 36 - (values - values.min()) / (span if span else 1) * 30
    x = np.linspace(0, 260, len(values))
    points = ' '.join(f'{a:.1f},{b:.1f}' for a, b in zip(x, y))
    return f'<svg class="sparkline" viewBox="0 0 260 44" preserveAspectRatio="none" role="img" aria-label="Trend across the selected window"><polygon points="0,44 {points} 260,44" fill="{color}" opacity=".09"/><polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def metric_card(col, metric, values):
    meta = METRICS[col]
    latest = metric['current_latest']
    passes = latest >= metric['target'] if metric['higher_is_better'] else latest <= metric['target']
    symbol = '≥' if metric['higher_is_better'] else '≤'
    return f'''<article class="metric-card" style="--metric:{meta['color']}">
      <div class="metric-top"><span class="metric-icon">{icon(meta['icon'])}</span><span>{meta['name']}</span>
      <span class="reading-status {'good' if passes else 'bad'}">{'In target' if passes else 'Out of target'}</span></div>
      <div class="metric-value">{format_value(latest, col)}<span>{meta['unit']}</span></div>
      <div class="metric-context">Latest reading <span>Target {symbol} {metric['target']:g} {meta['unit']}</span></div>
      {sparkline(values, meta['color'])}
      <div class="metric-bottom"><span>Window compliance</span><strong>{metric['compliance_pct']:.1f}%</strong></div>
    </article>'''


def hero(score, violations, source, window, rows, interval):
    state = 'All checks passing' if violations == 0 else 'Attention needed'
    return f'''<section class="hero">
      <div class="hero-copy"><div class="eyebrow">CLOUD OBSERVABILITY <span>/</span> SLA MONITOR</div>
      <h1>Clarity for every cloud signal.</h1><p>Your reliability, performance, and incidents. One connected view.</p>
      <div class="hero-tags"><span><i class="live-dot"></i>{escape(source)}</span><span>{escape(window)}</span>
      <span>{rows:,} samples · {interval} min resolution</span></div></div>
      <div class="hero-score"><div class="score-orbit" style="--score:{score * 3.6:.2f}deg"><div><strong>{score:.1f}<small>%</small></strong><span>CHECKS PASSING</span></div></div>
      <div class="hero-state">{state}</div></div>
    </section>'''


def compliance_panel(compliance, rows):
    body = ''
    for col, m in compliance['metrics'].items():
        color = METRICS[col]['color']
        failures = round(rows * (100 - m['compliance_pct']) / 100)
        body += f'''<div class="compliance-item"><div><span><i style="background:{color}"></i>{METRICS[col]['name']}</span><strong>{m['compliance_pct']:.1f}%</strong></div>
        <div class="progress-track"><span style="width:{m['compliance_pct']}%;background:{color}"></span></div>
        <small>{failures:,} of {rows:,} samples outside target</small></div>'''
    return f'<div class="compliance-list">{body}</div>'


def base_figure(fig, height=290):
    fig.update_layout(template='none', height=height, paper_bgcolor='rgba(0,0,0,0)',
                      plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=6, r=12, t=20, b=12),
                      font=dict(family='Segoe UI, sans-serif', size=12),
                      hovermode='x unified', hoverlabel=dict(namelength=-1),
                      legend=dict(orientation='h', x=0, y=1.12, font=dict(size=11)),
                      uirevision='keep-view', dragmode='zoom')
    fig.update_xaxes(showgrid=False, zeroline=False, showline=False, automargin=True,
                     tickformat='%H:%M\n%b %d', nticks=6, tickfont=dict(size=11))
    fig.update_yaxes(gridcolor='rgba(125,145,180,.16)', zeroline=False, automargin=True,
                     tickfont=dict(size=11), fixedrange=False)
    return fig


def telemetry_figure(frame, col, target, show_breaches=True, smooth=False):
    meta = METRICS[col]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame['timestamp'], y=frame[col], name=meta['name'],
                            mode='lines', line=dict(color=meta['color'], width=2.8),
                            fill='tozeroy', fillcolor=hex_rgba(meta['color'], .16),
                            fillgradient=dict(type='vertical', colorscale=[[0, hex_rgba(meta['color'], 0)], [1, hex_rgba(meta['color'], .34)]]),
                            hovertemplate=f'%{{y:.4g}} {meta["unit"]}<extra>{meta["name"]}</extra>'))
    if smooth:
        fig.add_trace(go.Scatter(x=frame['timestamp'], y=frame[col].rolling(12, min_periods=1).mean(),
                                name='12-sample average', mode='lines',
                                line=dict(color='#E4A23B', width=2.5)))
    breach = frame[col] < target if col in ('uptime_pct', 'availability_pct') else frame[col] > target
    if show_breaches and breach.any():
        fig.add_trace(go.Scatter(x=frame.loc[breach, 'timestamp'], y=frame.loc[breach, col],
                                name='Outside target', mode='markers',
                                marker=dict(color='#F16A82', size=6, line=dict(width=1, color='#FFFFFF'))))
    fig.add_hline(y=target, line_dash='dot', line_color='#8C96B2', line_width=1.3,
                  annotation_text=f'Target {target:g} {meta["unit"]}',
                  annotation_position='top right', annotation_font_size=10)
    low = min(float(frame[col].min()), target)
    high = max(float(frame[col].max()), target)
    pad = max((high - low) * .18, abs(target) * .00015, .001)
    fig.update_yaxes(range=[max(0, low - pad), min(100, high + pad) if col != 'response_time_ms' else high + pad],
                     title_text=meta['unit'])
    return base_figure(fig, 330)


def hex_rgba(color, opacity):
    return f'rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},{opacity})'


def traffic_figure(frame):
    fig = go.Figure(go.Bar(x=frame['timestamp'], y=frame['request_volume'],
                           marker=dict(color=frame['request_volume'],
                                       colorscale=[[0, '#9A4DFF'], [.5, '#6475FF'], [1, '#00E2C3']]),
                           name='Requests / sample', hovertemplate='%{y:,.0f} requests<extra></extra>'))
    fig.update_layout(bargap=.25)
    return base_figure(fig, 235)


def heatmap_figure(heat):
    fig = go.Figure(go.Heatmap(z=heat.values, x=list(range(24)), y=list(heat.index),
                              zmin=0, zmax=100, xgap=3, ygap=3,
                              colorscale=[[0, '#C6F7E7'], [.01, '#7BE1C5'], [.15, '#7964FA'],
                                          [.4, '#C54AF1'], [.7, '#F4449A'], [1, '#FF5C50']],
                              hoverongaps=False, showscale=False,
                              hovertemplate='%{y} · %{x}:00<br>%{z:.1f}% of checks failed<extra></extra>'))
    fig = base_figure(fig, min(540, max(140, 65 + len(heat) * 23)))
    fig.update_xaxes(tickmode='array', tickvals=list(range(0, 24, 2)),
                     ticktext=[f'{hour:02d}' for hour in range(0, 24, 2)])
    fig.update_yaxes(type='category', autorange='reversed', showgrid=False)
    fig.update_layout(margin=dict(l=0, r=0, t=8, b=0), hovermode='closest')
    return fig


def radar_figure(compliance):
    labels = [m['short'] for m in METRICS.values()]
    values = [compliance['metrics'][col]['compliance_pct'] for col in METRICS]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=[100]*5, theta=labels + labels[:1], mode='lines',
                                 line=dict(color='rgba(140,140,140,.38)', width=1, dash='dot'),
                                 name='Perfect compliance', hoverinfo='skip'))
    fig.add_trace(go.Scatterpolar(r=values + values[:1], theta=labels + labels[:1],
                                 mode='lines+markers', fill='toself', fillcolor='rgba(145,98,255,.22)',
                                 line=dict(color='#A276FF', width=3),
                                 marker=dict(size=9, color=[m['color'] for m in METRICS.values()] + ['#9162FF']),
                                 name='Compliance', hovertemplate='%{theta}: %{r:.2f}%<extra></extra>'))
    fig.update_layout(template='none', height=330, showlegend=False,
                      paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=40, r=45, t=25, b=20),
                      polar=dict(bgcolor='rgba(0,0,0,0)',
                                 radialaxis=dict(range=[0,100], tickvals=[25,50,75,100],
                                                 ticksuffix='%', tickfont=dict(size=9),
                                                 gridcolor='rgba(135,135,135,.22)', showline=False),
                                 angularaxis=dict(gridcolor='rgba(135,135,135,.22)',
                                                  linecolor='rgba(135,135,135,.2)', tickfont=dict(size=11))))
    return fig


def distribution_figure(frame, target):
    values = frame['response_time_ms'].to_numpy()
    _, edges = np.histogram(values, bins=min(32, max(4, int(np.sqrt(len(values))))))
    centers = (edges[1:] + edges[:-1]) / 2
    fig = go.Figure()
    for subset, label, color in [(values[values <= target], 'In target', '#00B8CF'),
                                  (values[values > target], 'Outside target', '#F44076')]:
        counts, _ = np.histogram(subset, bins=edges)
        fig.add_trace(go.Bar(x=centers, y=counts, width=np.diff(edges)*.84,
                             name=label, marker=dict(color=color, line=dict(width=0), opacity=.9),
                             customdata=np.column_stack([edges[:-1], edges[1:]]),
                             hovertemplate='%{customdata[0]:.1f}–%{customdata[1]:.1f} ms<br>%{y} samples<extra>%{fullData.name}</extra>'))
    # Quantiles describe latency values, independent of the histogram bins.
    for value, label, color, position in [
        (float(np.median(values)), 'Median', '#00BE88', 'top left'),
        (float(np.percentile(values,95)), 'P95', '#AA7BFF', 'top right'),
        (target, 'SLA', '#F44076', 'bottom right')]:
        fig.add_vline(x=value, line_color=color, line_dash='dot', line_width=2,
                      annotation_text=f'{label} {value:.1f} ms', annotation_position=position,
                      annotation_font=dict(color=color,size=11))
    fig.update_xaxes(title_text='Response time (ms)', tickformat='.0f')
    fig.update_yaxes(title_text='Samples')
    fig = base_figure(fig, 280)
    fig.update_layout(showlegend=True, barmode='stack', hovermode='closest')
    fig.update_xaxes(tickformat='.0f', range=[0, max(float(edges[-1]),target)*1.1])
    return fig


def comparison_figure(frame, targets):
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=.07,
                        subplot_titles=[m['name'] + f" ({m['unit']})" for m in METRICS.values()])
    for row, (col, meta) in enumerate(METRICS.items(),1):
        fig.add_trace(go.Scatter(x=frame['timestamp'], y=frame[col], mode='lines',
                                 name=meta['name'], line=dict(color=meta['color'],width=2),
                                 fill='tozeroy', fillcolor=hex_rgba(meta['color'], .12)), row=row, col=1)
        fig.add_hline(y=targets[col], row=row, col=1, line_dash='dot', line_color='#888888')
    fig = base_figure(fig, 560)
    fig.update_layout(showlegend=False, margin=dict(l=15,r=10,t=28,b=10))
    fig.update_annotations(font_size=11)
    return fig


def incident_ribbon(frame, targets):
    failures = sum((frame[col].lt(targets[col]) if col in ('uptime_pct','availability_pct')
                    else frame[col].gt(targets[col])).astype(int) for col in METRICS)
    # Preserve the worst sampled state in each tile rather than average away spikes.
    groups = np.array_split(np.arange(len(frame)), min(96,len(frame)))
    colors = ['#00BE88','#9B6AFF','#E449D3','#F44076','#FF574F']
    tiles = ''
    for group in groups:
        number = int(failures.iloc[group].max())
        first, last = frame.timestamp.iloc[group[0]], frame.timestamp.iloc[group[-1]]
        end_label = last.strftime('%H:%M' if first.date() == last.date() else '%d %b %H:%M')
        title = escape(f'{first:%d %b %H:%M}–{end_label} IST · up to {number}/4 metrics outside target')
        tiles += f'<span class="pulse-tile" style="--pulse:{colors[number]}" tabindex="0" aria-label="{title}"><span class="pulse-tooltip">{title}</span></span>'
    healthy = int(failures.eq(0).sum())
    return f'<div class="pulse-grid">{tiles}</div><div class="pulse-meta"><span>{frame.timestamp.iloc[0]:%d %b, %H:%M} IST</span><strong>{healthy:,}/{len(frame):,} intervals passed all four checks</strong><span>{frame.timestamp.iloc[-1]:%d %b, %H:%M} IST</span></div><div class="pulse-legend">' + ''.join(f'<span><i style="background:{c}"></i>{i} breaches</span>' for i,c in enumerate(colors)) + '</div>'
