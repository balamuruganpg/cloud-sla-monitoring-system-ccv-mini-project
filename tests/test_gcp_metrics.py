import unittest

import pandas as pd
from google.cloud import monitoring_v3 as m

from gcp_metrics import fetch_gcp_metrics


def series(kind, value, code=None, timestamp='2026-10-30T10:00:00Z'):
    return m.TimeSeries(metric={'type': kind, 'labels': {'response_code': code} if code else {}},
                        points=[{'interval': {'end_time': pd.Timestamp(timestamp).to_pydatetime()}, 'value': value}])


class GcpDataTests(unittest.TestCase):
    def test_missing_streams_do_not_turn_into_healthy_placeholder_values(self):
        from gcp_metrics import assemble_gcp_frame
        with self.assertRaisesRegex(ValueError, 'Missing'):
            assemble_gcp_frame([], [], [], 5)

    def test_live_values_are_aligned_by_time_and_errors_derived_from_counts(self):
        from gcp_metrics import assemble_gcp_frame
        uptime = [series('uptime', {'bool_value': True}), series('uptime', {'bool_value': False})]
        latency = [series('latency', {'distribution_value': {'mean': 100, 'count': 10}}),
                   series('latency', {'distribution_value': {'mean': 200, 'count': 30}})]
        requests = [series('requests', {'int64_value': 80}, '200'), series('requests', {'int64_value': 20}, '500')]
        frame = assemble_gcp_frame(uptime, latency, requests, 5)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0].uptime_pct, 50)
        self.assertEqual(frame.iloc[0].response_time_ms, 175)
        self.assertEqual(frame.iloc[0].request_volume, 100)
        self.assertEqual(frame.iloc[0].error_rate_pct, 20)
        self.assertEqual(frame.iloc[0].timestamp, pd.Timestamp('2026-10-30T10:00:00Z'))

    def test_missing_project_has_clear_fallback(self):
        frame, reason = fetch_gcp_metrics('')
        self.assertIsNone(frame)
        self.assertIn('Project ID', reason)

    def test_outage_with_no_request_telemetry_is_not_silently_dropped(self):
        from gcp_metrics import assemble_gcp_frame
        uptime = [series('uptime', {'bool_value': True}),
                  series('uptime', {'bool_value': False}, timestamp='2026-10-30T10:05:00Z')]
        latency = [series('latency', {'distribution_value': {'mean': 100, 'count': 10}})]
        requests = [series('requests', {'int64_value': 10}, '200')]
        with self.assertRaisesRegex(ValueError, 'incomplete coverage'):
            assemble_gcp_frame(uptime, latency, requests, 5)


if __name__ == '__main__':
    unittest.main()
