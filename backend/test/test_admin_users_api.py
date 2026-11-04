import unittest

from flask import Flask

from database.db import db
from database.models import User
from web.pages import web_bp


class AdminUsersApiTestCase(unittest.TestCase):
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

            admin_root = User(username='admin_root', role='admin')
            admin_root.set_password('password123')
            admin_root.set_security_code('0001')

            admin_backup = User(username='admin_backup', role='admin')
            admin_backup.set_password('password123')
            admin_backup.set_security_code('0002')

            member = User(username='member_user', role='user')
            member.set_password('password123')
            member.set_security_code('1111')

            db.session.add_all([admin_root, admin_backup, member])
            db.session.commit()

            self.admin_root_id = admin_root.id
            self.member_id = member.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def _login(self, username, password='password123'):
        response = self.client.post('/api/web/login', json={
            'username': username,
            'password': password,
        })
        self.assertEqual(response.status_code, 200)

    def test_admin_users_endpoint_requires_login(self):
        response = self.client.get('/api/web/admin/users')
        self.assertEqual(response.status_code, 401)

    def test_non_admin_can_only_view_self_in_users_api(self):
        self._login('member_user')
        response = self.client.get('/api/web/admin/users')
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertFalse(payload.get('can_manage'))
        users = payload.get('users') or []
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].get('username'), 'member_user')
        self.assertTrue(users[0].get('is_current_user'))

    def test_non_admin_cannot_create_user(self):
        self._login('member_user')
        response = self.client.post('/api/web/admin/users', json={
            'username': 'blocked_user',
            'organization': '受限单位',
            'password': 'abc12345',
            'confirm_password': 'abc12345',
            'security_code': '1122',
            'role': 'user',
        })
        self.assertEqual(response.status_code, 403)

    def test_admin_can_list_users(self):
        self._login('admin_root')

        response = self.client.get('/api/web/admin/users')
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload.get('summary', {}).get('total'), 3)
        self.assertEqual(payload.get('summary', {}).get('admin_count'), 2)

        users = payload.get('users') or []
        self.assertEqual(len(users), 3)
        self.assertTrue(any(item.get('is_current_user') for item in users))
        self.assertTrue(all('organization' in item for item in users))

    def test_admin_can_create_user_and_update_role(self):
        self._login('admin_root')

        create_resp = self.client.post('/api/web/admin/users', json={
            'username': 'new_member',
            'organization': '测试单位B',
            'password': 'abc12345',
            'confirm_password': 'abc12345',
            'security_code': '2233',
            'role': 'user',
        })
        self.assertEqual(create_resp.status_code, 200)

        with self.app.app_context():
            created = User.query.filter_by(username='new_member').first()
            self.assertIsNotNone(created)
            assert created is not None
            self.assertEqual(created.role, 'user')
            self.assertEqual(created.organization, '测试单位B')
            created_id = created.id

        update_resp = self.client.post(f'/api/web/admin/users/{created_id}/role', json={'role': 'admin'})
        self.assertEqual(update_resp.status_code, 200)

        with self.app.app_context():
            updated = db.session.get(User, created_id)
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.role, 'admin')

    def test_admin_can_update_other_member_profile(self):
        self._login('admin_root')

        response = self.client.post(f'/api/web/admin/users/{self.member_id}/update', json={
            'username': 'member_user_updated',
            'organization': '测试单位C',
        })
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload.get('user', {}).get('username'), 'member_user_updated')
        self.assertEqual(payload.get('user', {}).get('organization'), '测试单位C')

        with self.app.app_context():
            updated = db.session.get(User, self.member_id)
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.username, 'member_user_updated')
            self.assertEqual(updated.organization, '测试单位C')

    def test_admin_can_update_other_member_profile_and_password(self):
        self._login('admin_root')

        response = self.client.post(f'/api/web/admin/users/{self.member_id}/update', json={
            'username': 'member_user',
            'organization': '测试单位C',
            'password': 'newpass123',
            'confirm_password': 'newpass123',
        })
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            updated = db.session.get(User, self.member_id)
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertTrue(updated.check_password('newpass123'))

    def test_admin_update_profile_rejects_invalid_password_pair(self):
        self._login('admin_root')

        response = self.client.post(f'/api/web/admin/users/{self.member_id}/update', json={
            'username': 'member_user',
            'organization': '测试单位C',
            'password': '123',
            'confirm_password': '456',
        })
        self.assertEqual(response.status_code, 400)

    def test_non_admin_cannot_update_member_profile(self):
        self._login('member_user')

        response = self.client.post(f'/api/web/admin/users/{self.admin_root_id}/update', json={
            'username': 'blocked_admin',
            'organization': '受限单位',
        })
        self.assertEqual(response.status_code, 403)

    def test_non_admin_can_update_self_profile(self):
        self._login('member_user')

        response = self.client.post('/api/web/users/me/update', json={
            'username': 'member_self_updated',
            'organization': '个人中心单位',
            'password': 'newpass123',
            'confirm_password': 'newpass123',
        })
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload.get('user', {}).get('username'), 'member_self_updated')
        self.assertEqual(payload.get('user', {}).get('organization'), '个人中心单位')

        with self.app.app_context():
            updated = User.query.filter_by(username='member_self_updated').first()
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertTrue(updated.check_password('newpass123'))

    def test_admin_update_profile_rejects_duplicate_username(self):
        self._login('admin_root')

        response = self.client.post(f'/api/web/admin/users/{self.member_id}/update', json={
            'username': 'admin_backup',
            'organization': '测试单位D',
        })
        self.assertEqual(response.status_code, 409)

    def test_admin_cannot_delete_self(self):
        self._login('admin_root')
        response = self.client.post(f'/api/web/admin/users/{self.admin_root_id}/delete', json={})
        self.assertEqual(response.status_code, 400)

    def test_admin_can_delete_other_user(self):
        self._login('admin_root')
        response = self.client.post(f'/api/web/admin/users/{self.member_id}/delete', json={})
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            self.assertIsNone(db.session.get(User, self.member_id))


if __name__ == '__main__':
    unittest.main()