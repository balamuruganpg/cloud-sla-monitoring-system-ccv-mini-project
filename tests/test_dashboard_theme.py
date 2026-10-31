import datetime as dt
import unittest
from urllib.parse import parse_qs, urlsplit


class AppearanceTests(unittest.TestCase):
    def test_theme_navigation_preserves_controls_and_snapshot(self):
        from dashboard_theme import appearance_url, restored_controls
        state = {'window': 'Last 7 days', 'seed': 19, 'stress': True,
                 'target_latency': 180.0, 'navigation': 'Overview',
                 'gcp_project': 'production-observability',
                 'snapshot_end': dt.datetime(2026, 10, 31, 12, tzinfo=dt.timezone.utc)}
        params = parse_qs(urlsplit(appearance_url('light', state)).query)
        self.assertEqual(params['embed_options'], ['light_theme'])
        restored = restored_controls(params['controls'][0])
        self.assertEqual(restored['target_latency'], 180.0)
        self.assertEqual(restored['snapshot_end'], state['snapshot_end'])
        self.assertTrue(restored['stress'])
        self.assertEqual(restored['gcp_project'], 'production-observability')

    def test_invalid_url_controls_are_ignored(self):
        from dashboard_theme import restored_controls
        self.assertEqual(restored_controls('{"target_latency":-12,"seed":"oops","source":"unknown"}'), {})
        self.assertEqual(restored_controls('not-json'), {})


if __name__ == '__main__':
    unittest.main()
