import datetime as dt
import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / 'app.py')


class DashboardInteractionTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        return app

    def test_threshold_changes_evaluate_same_telemetry(self):
        app = self.app()
        app.get_by_key('navigation').set_value('Data & guide').run()
        original = app.dataframe[0].value.copy()
        app.slider(key='target_latency').set_value(50.0).run()
        self.assertFalse(app.exception)
        pd.testing.assert_frame_equal(original, app.dataframe[0].value)

    def test_stress_mode_and_long_windows(self):
        app = self.app()
        app.toggle(key='stress').set_value(True).run()
        self.assertFalse(app.exception)
        app.selectbox(key='window').select('Last 30 days').run()
        self.assertFalse(app.exception)
        app.get_by_key('navigation').set_value('Data & guide').run()
        self.assertEqual(len(app.dataframe[0].value), 1440)

    def test_incident_filters_and_empty_state(self):
        app = self.app()
        app.get_by_key('navigation').set_value('Incidents').run()
        app.selectbox(key='incident_metric').select('Response Time').run()
        incidents = app.dataframe[0].value
        self.assertTrue(incidents.Metric.eq('Response Time').all())
        app.text_input(key='incident_search').set_value('no-such-incident').run()
        self.assertFalse(app.exception)
        self.assertIn('No incidents match', app.success[0].value)

    def test_live_without_project_falls_back_visibly(self):
        app = self.app()
        app.get_by_key('source').set_value('Live GCP').run()
        self.assertFalse(app.exception)
        self.assertIn('Simulation fallback', app.warning[0].value)
        self.assertTrue(app.toggle(key='stress').disabled)

    def test_custom_dates_partial_and_too_long_do_not_crash(self):
        app = self.app()
        app.selectbox(key='window').select('Custom dates').run()
        self.assertFalse(app.exception)
        today = app.session_state['snapshot_end'].date()
        app.date_input(key='dates').set_value((today,)).run()
        self.assertFalse(app.exception)
        self.assertIn('both', app.info[0].value)
        app.date_input(key='dates').set_value((today - dt.timedelta(days=61), today)).run()
        self.assertIn('60', app.info[0].value)


if __name__ == '__main__':
    unittest.main()

