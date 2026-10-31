import unittest
from datetime import datetime

import numpy as np

from dashboard_ui import METRICS, comparison_figure, distribution_figure, radar_figure
from sla_simulator import generate_metrics, DEFAULT_SLA_TARGETS
from sla_analyzer import evaluate_compliance


class VisualDataTests(unittest.TestCase):
    def setUp(self):
        self.frame = generate_metrics(hours=24, end_time=datetime(2026,10,31,12))

    def test_distribution_accounts_for_every_observation(self):
        figure = distribution_figure(self.frame, 200)
        self.assertEqual(sum(sum(trace.y) for trace in figure.data), 288)
        self.assertEqual(sum(figure.data[1].y), int(self.frame.response_time_ms.gt(200).sum()))
        # Median, P95 and SLA markers retain their actual coordinates.
        self.assertAlmostEqual(figure.layout.shapes[0].x0, float(np.median(self.frame.response_time_ms)))
        self.assertEqual(figure.layout.shapes[2].x0, 200)

    def test_comparison_preserves_units_and_values(self):
        figure = comparison_figure(self.frame, DEFAULT_SLA_TARGETS)
        self.assertEqual(len(figure.data), 4)
        for trace, col in zip(figure.data, METRICS):
            np.testing.assert_array_equal(trace.y, self.frame[col])
        self.assertEqual(len(figure.layout.shapes), 4)

    def test_radar_has_honest_zero_to_hundred_scale(self):
        compliance = evaluate_compliance(self.frame)
        figure = radar_figure(compliance)
        self.assertEqual(list(figure.layout.polar.radialaxis.range), [0,100])
        self.assertEqual(list(figure.data[1].r)[:4], [compliance['metrics'][col]['compliance_pct'] for col in METRICS])


if __name__ == '__main__':
    unittest.main()
