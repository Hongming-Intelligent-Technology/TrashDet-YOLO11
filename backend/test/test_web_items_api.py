import unittest
from datetime import datetime

from flask import Flask

from database.db import db
from database.models import DetectItem, DetectTask, OpsLog, User
from web.pages import web_bp


class WebItemsApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SECRET_KEY': 'test-secret',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        self.app.register_blueprint(web_bp)

        with self.app.app_context():
            db.create_all()

            user = User(username='tester')
            user.set_password('password123')
            user.set_security_code('1234')
            other_user = User(username='tester_other')
            other_user.set_password('password123')
            other_user.set_security_code('5678')
            db.session.add(user)
            db.session.add(other_user)
            db.session.flush()

            task = DetectTask(
                source_type='parser',
                source_path='ingest://abc',
                result_path='static/results/a.jpg',
                status='DONE',
                user_id=user.id,
                created_at=datetime.now(),
                latitude=10.0,
                longitude=20.0,
                device_id='parser-01',
            )
            other_task = DetectTask(
                source_type='parser',
                source_path='ingest://other',
                result_path='static/results/b.jpg',
                status='DONE',
                user_id=other_user.id,
                created_at=datetime.now(),
                latitude=11.0,
                longitude=21.0,
                device_id='parser-02',
            )
            db.session.add(task)
            db.session.add(other_task)
            db.session.flush()

            db.session.add_all([
                DetectItem(task_id=task.id, label='Plastic', confidence=0.9, x1=1, y1=1, x2=11, y2=11, area=100),
                DetectItem(task_id=task.id, label='Metal', confidence=0.8, x1=2, y1=2, x2=12, y2=12, area=100),
                DetectItem(task_id=other_task.id, label='Glass', confidence=0.7, x1=3, y1=3, x2=13, y2=13, area=100),
            ])
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def _login(self):
        response = self.client.post('/api/web/login', json={
            'username': 'tester',
            'password': 'password123',
        })
        self.assertEqual(response.status_code, 200)

    def test_items_endpoint_requires_login(self):
        response = self.client.get('/api/web/items')
        self.assertEqual(response.status_code, 401)

    def test_items_endpoint_returns_item_rows(self):
        self._login()
        response = self.client.get('/api/web/items?page=1')
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload.get('pagination', {}).get('total'), 2)

        items = payload.get('items') or []
        self.assertEqual(len(items), 2)
        self.assertIn('task_id', items[0])
        self.assertIn('label', items[0])
        self.assertIn('display_location', items[0])
        self.assertTrue(all(item.get('device_id') == 'parser-01' for item in items))

    def test_client_log_endpoint_persists_ops_log(self):
        self._login()

        response = self.client.post('/api/web/client-log', json={
            'message': '机器人控制命令已下发',
            'category': 'success',
            'path': '/robot/1',
            'source': 'flash',
        })
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))

        with self.app.app_context():
            log_row = db.session.get(OpsLog, payload.get('id'))
            self.assertIsNotNone(log_row)
            self.assertIn('机器人控制命令已下发', log_row.action)


if __name__ == '__main__':
    unittest.main()
