import datetime as dt
import unittest

import pandas as pd

from sla_simulator import generate_metrics


class SamplingTests(unittest.TestCase):
    def test_samples_really_are_five_minutes_apart(self):
        frame = generate_metrics(hours=24, end_time=dt.datetime(2026, 10, 30, 12))
        self.assertEqual(len(frame), 288)
        self.assertTrue(frame.timestamp.diff().dropna().eq(pd.Timedelta(minutes=5)).all())


class DashboardDataTests(unittest.TestCase):
    def test_budget_integrates_partial_availability_loss(self):
        from dashboard_data import error_budget
        frame = pd.DataFrame({'timestamp': pd.date_range('2026-10-30', periods=2, freq='5min'),
                              'availability_pct': [100.0, 90.0]})
        budget = error_budget(frame, 99.0, 5)
        self.assertAlmostEqual(budget['allowed_minutes'], 0.1)
        self.assertAlmostEqual(budget['consumed_minutes'], 0.5)
        self.assertEqual(budget['remaining_pct'], 0.0)
        self.assertAlmostEqual(budget['burn_rate'], 5.0)

    def test_zero_budget_is_explicit(self):
        from dashboard_data import error_budget
        frame = pd.DataFrame({'timestamp': pd.date_range('2026-10-30', periods=2, freq='5min'),
                              'availability_pct': [100.0, 100.0]})
        self.assertEqual(error_budget(frame, 100.0, 5)['remaining_pct'], 100.0)
        frame.loc[1, 'availability_pct'] = 99.0
        self.assertEqual(error_budget(frame, 100.0, 5)['burn_rate'], float('inf'))

    def test_missing_telemetry_is_not_counted_as_observed_downtime(self):
        from dashboard_data import error_budget
        frame = pd.DataFrame({'timestamp': pd.to_datetime(['2026-10-30 10:00', '2026-10-30 11:00']),
                              'availability_pct': [100.0, 90.0]})
        budget = error_budget(frame, 99.0, 5)
        self.assertAlmostEqual(budget['consumed_minutes'], 0.5)
        self.assertEqual(budget['observed_minutes'], 10.0)

    def test_custom_window_over_sixty_days_is_rejected(self):
        from dashboard_data import custom_window
        with self.assertRaisesRegex(ValueError, '60'):
            custom_window((dt.date(2026, 1, 1), dt.date(2026, 4, 1)), dt.datetime(2026, 10, 30))

    def test_custom_window_requires_both_dates(self):
        from dashboard_data import custom_window
        with self.assertRaises(ValueError):
            custom_window((dt.date(2026, 10, 1),), dt.datetime(2026, 10, 30))

    def test_today_ends_at_now_without_future_samples(self):
        from dashboard_data import custom_window
        start, end = custom_window((dt.date(2026, 10, 30), dt.date(2026, 10, 30)), dt.datetime(2026, 10, 30, 12))
        self.assertEqual(start, dt.datetime(2026, 10, 30))
        self.assertEqual(end, dt.datetime(2026, 10, 30, 12))

    def test_heatmap_keeps_days_separate_and_missing_hours_missing(self):
        from dashboard_data import breach_heatmap
        from sla_simulator import DEFAULT_SLA_TARGETS
        frame = pd.DataFrame({'timestamp': pd.to_datetime(['2026-10-29 23:00', '2026-10-30 00:00']),
                              'uptime_pct': [99.0, 100.0], 'response_time_ms': [100, 100],
                              'error_rate_pct': [0.0, 0.0], 'availability_pct': [100.0, 100.0]})
        heat = breach_heatmap(frame, DEFAULT_SLA_TARGETS)
        self.assertEqual(list(heat.index), ['Oct 29', 'Oct 30'])
        self.assertEqual(heat.loc['Oct 29', 23], 25.0)
        self.assertEqual(heat.loc['Oct 30', 0], 0.0)
        self.assertTrue(pd.isna(heat.loc['Oct 29', 0]))


if __name__ == '__main__':
    unittest.main()
