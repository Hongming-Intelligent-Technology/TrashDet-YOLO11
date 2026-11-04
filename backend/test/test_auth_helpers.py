import unittest

from flask import Flask, jsonify

from database.db import db
from database.models import User
from services.auth import admin_required, get_session_user, is_admin_user, login_required


class AuthHelpersTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SECRET_KEY': 'test-secret',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)

        @self.app.route('/member-only')
        @login_required
        def member_only():
            return jsonify({'ok': True, 'user': get_session_user().username})

        @self.app.route('/admin-only')
        @admin_required
        def admin_only():
            return jsonify({'ok': True})

        with self.app.app_context():
            db.create_all()
            admin = User(username='admin_user', role='admin')
            admin.set_password('password123')
            admin.set_security_code('0001')
            member = User(username='member_user', role='user')
            member.set_password('password123')
            member.set_security_code('0002')
            db.session.add_all([admin, member])
            db.session.commit()
            self.admin_id = admin.id
            self.member_id = member.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def _login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id

    def test_is_admin_user(self):
        self.assertFalse(is_admin_user(None))
        with self.app.app_context():
            self.assertTrue(is_admin_user(db.session.get(User, self.admin_id)))
            self.assertFalse(is_admin_user(db.session.get(User, self.member_id)))

    def test_login_required_rejects_anonymous(self):
        response = self.client.get('/member-only')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()['ok'])

    def test_login_required_allows_member(self):
        self._login_as(self.member_id)
        response = self.client.get('/member-only')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['user'], 'member_user')

    def test_admin_required_rejects_anonymous_and_member(self):
        self.assertEqual(self.client.get('/admin-only').status_code, 401)
        self._login_as(self.member_id)
        self.assertEqual(self.client.get('/admin-only').status_code, 403)

    def test_admin_required_allows_admin(self):
        self._login_as(self.admin_id)
        self.assertEqual(self.client.get('/admin-only').status_code, 200)

    def test_unknown_session_user_is_anonymous(self):
        self._login_as(99999)
        self.assertEqual(self.client.get('/member-only').status_code, 401)


if __name__ == '__main__':
    unittest.main()
