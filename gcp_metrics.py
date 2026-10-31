"""Read-only Google Cloud Monitoring ingestion with explicit simulation fallback.

Raw API points are aligned by timestamp. Missing streams are never replaced with
fabricated healthy values. Availability shares the uptime-check observations.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

logger = logging.getLogger(__name__)
HAS_GCP_LIBS = False
try:
    from google.cloud import monitoring_v3
    from google.api_core.exceptions import GoogleAPIError, PermissionDenied, NotFound
    from google.auth.exceptions import DefaultCredentialsError
    HAS_GCP_LIBS = True
except ImportError:
    pass


def check_gcp_environment():
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    project = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    exists = bool(path and os.path.isfile(path))
    return dict(has_libraries=HAS_GCP_LIBS, credentials_path=path,
                credentials_exist=exists, project_id=project,
                is_configured=HAS_GCP_LIBS and (exists or bool(project)))


def assemble_gcp_frame(uptime_series, latency_series, request_series, interval_minutes):
    """Aggregate observed BOOL, DISTRIBUTION and DELTA points into common buckets."""
    if not uptime_series or not latency_series or not request_series:
        raise ValueError("Missing uptime checks, latency, or request-count telemetry.")
    rows = []
    for kind, streams in (("uptime", uptime_series), ("latency", latency_series), ("requests", request_series)):
        for stream in streams:
            labels = dict(stream.metric.labels)
            code = labels.get("response_code") or labels.get("response_code_class")
            if kind == "requests" and code is None:
                raise ValueError("Missing HTTP response-code labels; error rate cannot be calculated.")
            for point in stream.points:
                bucket = pd.Timestamp(point.interval.end_time).ceil(f"{interval_minutes}min")
                value = point.value
                value_kind = value._pb.WhichOneof("value")
                if kind == "uptime":
                    if value_kind not in ("bool_value", "double_value"):
                        continue
                    number = float(value.bool_value if value_kind == "bool_value" else value.double_value)
                    weight = 1
                elif kind == "latency":
                    if value_kind != "distribution_value" or value.distribution_value.count <= 0:
                        continue
                    number = float(value.distribution_value.mean)
                    weight = int(value.distribution_value.count)
                else:
                    if value_kind not in ("int64_value", "double_value"):
                        continue
                    number = float(value.int64_value if value_kind == "int64_value" else value.double_value)
                    weight = 1
                rows.append(dict(timestamp=bucket, kind=kind, value=number, weight=weight,
                                 errors=number if kind == "requests" and str(code).startswith("5") else 0))
    if not rows:
        raise ValueError("Missing numeric telemetry points.")
    raw = pd.DataFrame(rows)
    uptime = raw.loc[raw.kind.eq("uptime")].groupby("timestamp").value.mean().mul(100)
    latency = raw.loc[raw.kind.eq("latency")].copy()
    latency["weighted"] = latency.value * latency.weight
    latency = latency.groupby("timestamp")[["weighted", "weight"]].sum()
    latency = latency.weighted / latency.weight
    counts = raw.loc[raw.kind.eq("requests")].groupby("timestamp")[["value", "errors"]].sum()
    counts = counts.loc[counts.value.gt(0)]
    result = pd.concat([uptime.rename("uptime_pct"), latency.rename("response_time_ms"),
                        counts.value.rename("request_volume"),
                        counts.errors.div(counts.value).mul(100).rename("error_rate_pct")], axis=1)
    # An outage may remove request/latency telemetry while checks still fail.
    # Dropping partial rows would erase those failures and overstate reliability.
    if result.isna().any().any():
        raise ValueError("Missing aligned metric observations; incomplete coverage cannot be scored reliably.")
    if result.empty:
        raise ValueError("Missing overlapping observations across all required telemetry streams.")
    result["availability_pct"] = result["uptime_pct"]
    result["request_volume"] = result["request_volume"].round().astype(int)
    return result.sort_index().reset_index()[["timestamp", "uptime_pct", "response_time_ms",
                                               "error_rate_pct", "availability_pct", "request_volume"]]


def fetch_gcp_metrics(project_id, hours=24, interval_minutes=5, start_time=None, end_time=None):
    """Fetch uptime checks and Cloud Run (or HTTPS load-balancer) HTTP metrics.

    Each request selects one metric type, as required by Cloud Monitoring.
    Custom windows are respected. API errors and incomplete data return a reason.
    """
    if not project_id or not project_id.strip():
        return None, "GCP Project ID is required for live monitoring."
    if not HAS_GCP_LIBS:
        return None, "Google Cloud libraries are missing. Install requirements.txt."
    end = end_time or datetime.now(timezone.utc)
    start = start_time or end - timedelta(hours=hours)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start >= end or interval_minutes <= 0:
        return None, "The monitoring window and sampling interval must be positive."
    try:
        client = monitoring_v3.MetricServiceClient()
        time_interval = monitoring_v3.TimeInterval({"start_time": start, "end_time": end})

        def query(metric):
            return list(client.list_time_series(request={
                "name": f"projects/{project_id.strip()}",
                "filter": f'metric.type = "{metric}"',
                "interval": time_interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }, timeout=15, retry=None))

        uptime = query("monitoring.googleapis.com/uptime_check/check_passed")
        if not uptime:
            return None, "No uptime-check observations were found in this window."
        # Do not combine Cloud Run and its fronting load balancer: that double-counts requests.
        for request_metric, latency_metric in (
            ("run.googleapis.com/request_count", "run.googleapis.com/request_latencies"),
            ("loadbalancing.googleapis.com/https/request_count", "loadbalancing.googleapis.com/https/total_latencies"),
        ):
            requests = query(request_metric)
            if requests:
                latency = query(latency_metric)
                result = assemble_gcp_frame(uptime, latency, requests, interval_minutes)
                result = result.loc[result.timestamp.le(pd.Timestamp(end))]
                if result.empty:
                    return None, "No complete telemetry intervals were found in the selected window."
                result.attrs["request_source"] = request_metric
                return result, None
        return None, "No Cloud Run or HTTPS load-balancer request telemetry was found in this window."
    except DefaultCredentialsError:
        return None, "Google application credentials were not found. Configure application default credentials."
    except PermissionDenied:
        return None, "Permission denied. The configured account needs roles/monitoring.viewer."
    except NotFound:
        return None, f"Project '{project_id}' was not found."
    except (GoogleAPIError, ValueError) as exc:
        logger.warning("Cloud Monitoring data unavailable: %s", exc)
        return None, str(exc)
    except Exception as exc:
        logger.warning("Cloud Monitoring connection failed: %s", exc)
        return None, f"Cloud Monitoring connection failed: {exc}"
