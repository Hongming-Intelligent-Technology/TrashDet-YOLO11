import os
import unittest

from flask import Flask

from database.db import db
from database.models import User
from web.pages import web_bp


class AuthPagesTestCase(unittest.TestCase):
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
            user = User(username='tester')
            user.set_password('password123')
            user.set_security_code('1234')
            db.session.add(user)
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def test_register_page_accessible(self):
        resp = self.client.get('/register')
        self.assertEqual(resp.status_code, 200)

    def test_register_success(self):
        resp = self.client.post('/register', data={
            'username': 'new_user',
            'organization': '测试单位A',
            'password': 'abc12345',
            'confirm_password': 'abc12345',
            'security_code': '9988',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('注册成功'.encode('utf-8'), resp.data)

        with self.app.app_context():
            created = User.query.filter_by(username='new_user').first()
            self.assertIsNotNone(created)
            assert created is not None
            self.assertTrue(created.check_password('abc12345'))
            self.assertEqual(created.organization, '测试单位A')

    def test_login_success(self):
        resp = self.client.post('/login', data={
            'username': 'tester',
            'password': 'password123',
            'next': '/robot',
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/robot', resp.headers.get('Location', ''))

    def test_protected_page_redirect_when_not_logged_in(self):
        resp = self.client.get('/robot', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
