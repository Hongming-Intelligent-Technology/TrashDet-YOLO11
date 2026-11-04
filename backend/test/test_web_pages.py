import os
import unittest
from datetime import datetime

from flask import Flask

from database.db import db
from database.models import DetectTask, Robot, User
from web.pages import web_bp


class WebPagesTestCase(unittest.TestCase):
    def setUp(self):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        template_dir = os.path.join(base_dir, 'templates')

        self.app = Flask(__name__, template_folder=template_dir)
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
            task = DetectTask(
                source_type='image',
                source_path='static/uploads/a.jpg',
                result_path='static/results/a.jpg',
                status='DONE',
                created_at=datetime.now(),
                latitude=10.0,
                longitude=20.0,
            )
            robot = Robot(device_id='RB-1', name='Robot-1', status='OFFLINE')
            user = User(username='tester')
            user.set_password('password123')
            user.set_security_code('1234')
            admin_user = User(username='admin_user', role='admin')
            admin_user.set_password('password123')
            admin_user.set_security_code('5678')
            db.session.add_all([task, robot, user, admin_user])
            db.session.commit()
            self.task_id = task.id
            self.robot_id = robot.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def test_main_pages(self):
        for path in ['/login', '/register']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200)

    def test_pages_redirect_to_login_when_not_authenticated(self):
        for path in ['/', '/result', f'/result/{self.task_id}', '/upload', '/stats', '/robot', f'/robot/{self.robot_id}', '/users']:
            resp = self.client.get(path, follow_redirects=False)
            self.assertEqual(resp.status_code, 302)
            self.assertIn('/login', resp.headers.get('Location', ''))

    def test_protected_pages_after_login(self):
        login_resp = self.client.post('/login', data={
            'username': 'tester',
            'password': 'password123',
        }, follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)

        for path in ['/', '/result', '/upload', '/stats', '/robot', '/users']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200)

    def test_admin_can_access_users_page(self):
        login_resp = self.client.post('/login', data={
            'username': 'admin_user',
            'password': 'password123',
        }, follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)

        resp = self.client.get('/users')
        self.assertEqual(resp.status_code, 200)

    def test_detail_pages(self):
        login_resp = self.client.post('/login', data={
            'username': 'tester',
            'password': 'password123',
        }, follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)

        resp_task = self.client.get(f'/result/{self.task_id}')
        resp_robot = self.client.get(f'/robot/{self.robot_id}')
        self.assertEqual(resp_task.status_code, 200)
        self.assertEqual(resp_robot.status_code, 200)

    def test_non_admin_cannot_delete_result(self):
        login_resp = self.client.post('/login', data={
            'username': 'tester',
            'password': 'password123',
        }, follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)

        resp = self.client.post(f'/result/{self.task_id}/delete', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/result/{self.task_id}', resp.headers.get('Location', ''))

        with self.app.app_context():
            self.assertIsNotNone(db.session.get(DetectTask, self.task_id))

    def test_admin_can_delete_result(self):
        login_resp = self.client.post('/login', data={
            'username': 'admin_user',
            'password': 'password123',
        }, follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)

        resp = self.client.post(f'/result/{self.task_id}/delete', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/result', resp.headers.get('Location', ''))

        with self.app.app_context():
            self.assertIsNone(db.session.get(DetectTask, self.task_id))


if __name__ == '__main__':
    unittest.main()
