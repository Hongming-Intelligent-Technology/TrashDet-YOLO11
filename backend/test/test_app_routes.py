import unittest

from app import create_app
from database.db import db


class AppRoutesTestCase(unittest.TestCase):
    def setUp(self):
        # Use an isolated in-memory database instead of the local .env / runtime_config.yaml.
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        })
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_health_endpoint(self):
        resp = self.client.get('/health')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get('status'), 'ok')
        self.assertIn('version', payload)

    def test_404_api_error_shape(self):
        resp = self.client.get('/api/not-exists')
        self.assertEqual(resp.status_code, 404)
        payload = resp.get_json()
        self.assertFalse(payload.get('ok'))
        self.assertEqual(payload.get('code'), 404)


if __name__ == '__main__':
    unittest.main()
