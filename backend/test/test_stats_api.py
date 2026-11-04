import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from flask import Flask

from api.stats_api import stats_bp
import api.stats_api as stats_api
from database.db import db
from database.models import DetectItem, DetectTask, User


class HotspotsApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SECRET_KEY': 'test-secret',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })

        db.init_app(self.app)
        self.app.register_blueprint(stats_bp, url_prefix='/api/stats')

        with self.app.app_context():
            db.create_all()
            self._seed_hotspot_data()

        self.client = self.app.test_client()
        self._clear_stats_caches()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        self._clear_stats_caches()

    def _seed_hotspot_data(self):
        admin_user = User(username='admin_user', role='admin')
        admin_user.set_password('password123')
        admin_user.set_security_code('1111')
        user_1 = User(username='hotspot_user_1')
        user_1.set_password('password123')
        user_1.set_security_code('2222')
        user_2 = User(username='hotspot_user_2')
        user_2.set_password('password123')
        user_2.set_security_code('3333')
        db.session.add_all([admin_user, user_1, user_2])
        db.session.flush()

        self.admin_id = admin_user.id
        self.user_1_id = user_1.id
        self.user_2_id = user_2.id

        task_1 = DetectTask(
            source_type='image',
            source_path='static/uploads/a.jpg',
            result_path='static/results/a.jpg',
            status='DONE',
            user_id=user_1.id,
            latitude=33.485,
            longitude=111.945,
            created_at=datetime.now() - timedelta(days=1),
        )
        task_2 = DetectTask(
            source_type='image',
            source_path='static/uploads/b.jpg',
            result_path='static/results/b.jpg',
            status='DONE',
            user_id=user_2.id,
            latitude=34.325,
            longitude=114.515,
            created_at=datetime.now() - timedelta(days=2),
        )

        db.session.add_all([task_1, task_2])
        db.session.flush()

        db.session.add_all([
            DetectItem(task_id=task_1.id, label='Plastic', confidence=0.91, x1=1, y1=1, x2=10, y2=10, area=81),
            DetectItem(task_id=task_1.id, label='Plastic', confidence=0.86, x1=2, y1=2, x2=9, y2=9, area=49),
            DetectItem(task_id=task_2.id, label='Glass Bottle', confidence=0.88, x1=3, y1=3, x2=8, y2=8, area=25),
        ])
        db.session.commit()

    def _clear_stats_caches(self):
        with stats_api._summary_cache_lock:
            stats_api._summary_cache.clear()
        with stats_api._hotspot_cache_lock:
            stats_api._hotspot_cache.clear()
        with stats_api._hotspot_geo_cache_lock:
            stats_api._hotspot_geo_cache.clear()

    def _login_as(self, user_id):
        with self.client.session_transaction() as session_ctx:
            session_ctx['user_id'] = user_id

    def test_hotspots_requires_login(self):
        response = self.client.get('/api/stats/hotspots')
        self.assertEqual(response.status_code, 401)

    @patch('api.stats_api._resolve_hotspot_region')
    def test_hotspots_returns_perf_and_region_fields(self, mock_region):
        self._login_as(self.admin_id)
        mock_region.return_value = {
            'province': '河南省',
            'city': '南阳市',
            'district': '内乡县',
            'town': '城关镇',
            'road': '示例路',
            'display_name': '内乡县, 南阳市, 河南省, 中国',
        }

        response = self.client.get('/api/stats/hotspots')
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertIn('perf', payload)
        self.assertIn('query_ms', payload['perf'])
        self.assertIn('geocode_ms', payload['perf'])
        self.assertIn('total_ms', payload['perf'])
        self.assertFalse(payload['perf'].get('cache_hit'))

        hotspots = payload.get('hotspots') or []
        self.assertGreater(len(hotspots), 0)

        first = hotspots[0]
        self.assertIn('province', first)
        self.assertIn('city', first)
        self.assertIn('district', first)
        self.assertIn('town', first)
        self.assertIn('road', first)
        self.assertIn('display_name', first)

    @patch('api.stats_api._resolve_hotspot_region')
    def test_hotspots_cache_hit_on_second_request(self, mock_region):
        self._login_as(self.admin_id)
        mock_region.return_value = {
            'province': '河南省',
            'city': '南阳市',
            'district': '内乡县',
            'town': '',
            'road': '',
            'display_name': '内乡县, 南阳市, 河南省, 中国',
        }

        first_response = self.client.get('/api/stats/hotspots?lookback_days=90&top_k=6')
        self.assertEqual(first_response.status_code, 200)
        first_payload = first_response.get_json()
        self.assertTrue(first_payload.get('ok'))
        self.assertFalse(first_payload['perf'].get('cache_hit'))

        first_call_count = mock_region.call_count
        self.assertGreater(first_call_count, 0)

        second_response = self.client.get('/api/stats/hotspots?lookback_days=90&top_k=6')
        self.assertEqual(second_response.status_code, 200)
        second_payload = second_response.get_json()
        self.assertTrue(second_payload.get('ok'))
        self.assertTrue(second_payload['perf'].get('cache_hit'))

        # Cache hit should bypass geocode calls entirely.
        self.assertEqual(mock_region.call_count, first_call_count)

    @patch('api.stats_api.time.sleep')
    @patch('api.stats_api._nominatim_rate_limit')
    @patch('api.stats_api.requests.get')
    def test_resolve_hotspot_region_retries_and_short_caches_failure(self, mock_get, _mock_rate_limit, mock_sleep):
        mock_get.side_effect = [
            stats_api.requests.Timeout(),
            stats_api.requests.Timeout(),
            stats_api.requests.Timeout(),
        ]

        region = stats_api._resolve_hotspot_region(33.485, 111.945)

        self.assertEqual(region['display_name'], '')
        self.assertEqual(mock_get.call_count, stats_api.HOTSPOT_GEO_RETRY_COUNT + 1)
        self.assertEqual(mock_sleep.call_count, stats_api.HOTSPOT_GEO_RETRY_COUNT)

        cache_entry = stats_api._hotspot_geo_cache[(33.485, 111.945)]
        self.assertEqual(cache_entry['ttl'], stats_api.HOTSPOT_GEO_FAILURE_CACHE_TTL_SECONDS)

    @patch('api.stats_api._nominatim_rate_limit')
    @patch('api.stats_api.requests.get')
    def test_resolve_hotspot_region_uses_split_timeout_and_success_cache_ttl(self, mock_get, _mock_rate_limit):
        response = Mock()
        response.status_code = 200
        response.content = b'{}'
        response.json.return_value = {
            'display_name': '内乡县, 南阳市, 河南省, 中国',
            'address': {
                'state': '河南省',
                'city': '南阳市',
                'county': '内乡县',
                'town': '城关镇',
                'road': '示例路',
            },
        }
        mock_get.return_value = response

        region = stats_api._resolve_hotspot_region(34.325, 114.515)

        self.assertEqual(region['city'], '南阳市')
        self.assertEqual(region['display_name'], '内乡县, 南阳市, 河南省, 中国')
        self.assertEqual(mock_get.call_args.kwargs['timeout'], (
            stats_api.HOTSPOT_GEO_CONNECT_TIMEOUT_SECONDS,
            stats_api.HOTSPOT_GEO_READ_TIMEOUT_SECONDS,
        ))

        cache_entry = stats_api._hotspot_geo_cache[(34.325, 114.515)]
        self.assertEqual(cache_entry['ttl'], stats_api.HOTSPOT_GEO_CACHE_TTL_SECONDS)

    @patch('api.stats_api._resolve_hotspot_region')
    def test_hotspots_non_admin_only_uses_owned_records(self, mock_region):
        self._login_as(self.user_1_id)
        mock_region.return_value = {
            'province': '河南省',
            'city': '南阳市',
            'district': '内乡县',
            'town': '',
            'road': '',
            'display_name': '内乡县, 南阳市, 河南省, 中国',
        }

        response = self.client.get('/api/stats/hotspots')
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        summary = payload.get('summary') or {}
        self.assertEqual(summary.get('tasks_used'), 1)


if __name__ == '__main__':
    unittest.main()
