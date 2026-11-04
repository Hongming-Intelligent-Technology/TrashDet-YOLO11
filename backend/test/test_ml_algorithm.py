import unittest
from datetime import datetime, timedelta

from ml.hotspot_forecasting import build_hotspot_forecast


class HotspotForecastingTestCase(unittest.TestCase):
    def test_empty_records_returns_no_hotspots(self):
        payload = build_hotspot_forecast(records=[], lookback_days=30, top_k=5)
        self.assertEqual(payload['summary']['cells_analyzed'], 0)
        self.assertEqual(payload['hotspots'], [])
        self.assertTrue(payload['recommendations'])

    def test_records_generate_hotspots(self):
        now = datetime.now()
        records = [
            {
                'created_at': now - timedelta(days=1),
                'latitude': 33.48,
                'longitude': 111.94,
                'label': 'Plastic',
                'detection_count': 3,
                'task_count': 1,
            },
            {
                'created_at': now - timedelta(days=2),
                'latitude': 33.48,
                'longitude': 111.94,
                'label': 'Plastic',
                'detection_count': 2,
                'task_count': 1,
            },
            {
                'created_at': now - timedelta(days=1),
                'latitude': 34.32,
                'longitude': 114.51,
                'label': 'Glass Bottle',
                'detection_count': 1,
                'task_count': 1,
            },
        ]

        payload = build_hotspot_forecast(records=records, lookback_days=30, top_k=3)
        self.assertGreater(payload['summary']['cells_analyzed'], 0)
        self.assertGreater(len(payload['hotspots']), 0)

        first = payload['hotspots'][0]
        self.assertIn('rank', first)
        self.assertIn('risk_score', first)
        self.assertIn('dominant_labels', first)


if __name__ == '__main__':
    unittest.main()
