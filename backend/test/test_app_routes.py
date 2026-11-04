import os
import tempfile
import unittest

from app import create_app
from database.db import db


class AppRoutesTestCase(unittest.TestCase):
    def setUp(self):
        # Use an isolated in-memory database instead of the local runtime_config.yaml.
        self.temp_dir = tempfile.TemporaryDirectory()
        config_path = os.path.join(self.temp_dir.name, 'runtime_config.yaml')
        with open(config_path, 'w', encoding='utf-8') as fp:
            fp.write('database:\n  DATABASE_URL: "sqlite:///:memory:"\n')
        self.old_config_path = os.environ.get('BUSINESS_CONFIG_PATH')
        os.environ['BUSINESS_CONFIG_PATH'] = config_path
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        if self.old_config_path is None:
            os.environ.pop('BUSINESS_CONFIG_PATH', None)
        else:
            os.environ['BUSINESS_CONFIG_PATH'] = self.old_config_path
        self.temp_dir.cleanup()

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
