import unittest
from datetime import datetime, timedelta

from flask import Flask

import api.stats_api as stats_api
from api.stats_api import stats_bp
from database.db import db
from database.models import DetectItem, DetectTask, Robot, User


class StatsSummaryApiTestCase(unittest.TestCase):
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
            now = datetime.now()

            admin_user = User(username='admin_user', role='admin')
            admin_user.set_password('password123')
            admin_user.set_security_code('1111')
            user_1 = User(username='stats_user_1')
            user_1.set_password('password123')
            user_1.set_security_code('2222')
            user_2 = User(username='stats_user_2')
            user_2.set_password('password123')
            user_2.set_security_code('3333')
            db.session.add_all([admin_user, user_1, user_2])
            db.session.flush()

            self.admin_id = admin_user.id
            self.user_1_id = user_1.id
            self.user_2_id = user_2.id

            task_1 = DetectTask(
                source_type='image',
                source_path='a.jpg',
                result_path='ra.jpg',
                status='DONE',
                user_id=user_1.id,
                latitude=30.1,
                longitude=110.1,
                created_at=now - timedelta(days=1),
            )
            task_2 = DetectTask(
                source_type='image',
                source_path='b.jpg',
                result_path='rb.jpg',
                status='DONE',
                user_id=user_2.id,
                latitude=31.2,
                longitude=111.2,
                created_at=now,
            )
            db.session.add_all([task_1, task_2])
            db.session.flush()

            db.session.add_all([
                DetectItem(task_id=task_1.id, label='Plastic', confidence=0.9, x1=1, y1=1, x2=2, y2=2, area=1),
                DetectItem(task_id=task_2.id, label='Metal', confidence=0.8, x1=1, y1=1, x2=2, y2=2, area=1),
            ])

            robot_1 = Robot(device_id='RB_SUM_1', name='RB_SUM_1', status='ONLINE', owner_user_id=user_1.id, last_heartbeat=now)
            robot_2 = Robot(device_id='RB_SUM_2', name='RB_SUM_2', status='ONLINE', owner_user_id=user_2.id, last_heartbeat=now)
            db.session.add_all([robot_1, robot_2])
            db.session.commit()

        self.client = self.app.test_client()
        with stats_api._summary_cache_lock:
            stats_api._summary_cache.clear()

    def _login_as(self, user_id):
        with self.client.session_transaction() as session_ctx:
            session_ctx['user_id'] = user_id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        with stats_api._summary_cache_lock:
            stats_api._summary_cache.clear()

    def test_summary_requires_login(self):
        resp = self.client.get('/api/stats/summary')
        self.assertEqual(resp.status_code, 401)

    def test_summary_returns_expected_sections(self):
        self._login_as(self.admin_id)
        resp = self.client.get('/api/stats/summary')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()

        self.assertTrue(payload.get('ok'))
        self.assertIn('locations', payload)
        self.assertIn('pie_data', payload)
        self.assertIn('line_data', payload)
        self.assertIn('robot_list', payload)
        self.assertGreaterEqual(len(payload.get('locations') or []), 2)
        self.assertGreaterEqual(len(payload.get('pie_data') or []), 1)

    def test_summary_cache_hit(self):
        self._login_as(self.admin_id)
        first = self.client.get('/api/stats/summary')
        self.assertEqual(first.status_code, 200)

        second = self.client.get('/api/stats/summary')
        self.assertEqual(second.status_code, 200)

        with stats_api._summary_cache_lock:
            self.assertGreaterEqual(len(stats_api._summary_cache), 1)

    def test_summary_non_admin_only_sees_owned_data(self):
        self._login_as(self.user_1_id)

        resp = self.client.get('/api/stats/summary')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()

        self.assertTrue(payload.get('ok'))
        self.assertEqual(len(payload.get('locations') or []), 1)
        self.assertEqual(len(payload.get('robot_list') or []), 1)


if __name__ == '__main__':
    unittest.main()
