import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from flask import Flask

from api.train_api import train_bp
from api.train_helpers import _job_lock, _job_state
from database.db import db
from database.models import TrainJob, User


class TrainApiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SECRET_KEY': 'test-secret',
            'BASE_DIR': self.temp_dir.name,
            'YOLO_MODEL_PATH': os.path.join(self.temp_dir.name, 'default.pt'),
            'TRAIN_MAX_CONTENT_LENGTH': 64 * 1024 * 1024,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        self.app.register_blueprint(train_bp, url_prefix='/api/train')
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

        with open(self.app.config['YOLO_MODEL_PATH'], 'wb') as fp:
            fp.write(b'fake-pt')

        self.client = self.app.test_client()
        self._login_as(self.admin_id)
        self._reset_jobs()

    def _login_as(self, user_id):
        with self.client.session_transaction() as sess:
            if user_id is None:
                sess.pop('user_id', None)
            else:
                sess['user_id'] = user_id

    def tearDown(self):
        self._reset_jobs()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _reset_jobs(self):
        with _job_lock:
            _job_state['active_job_id'] = None
            _job_state['jobs'].clear()

    @staticmethod
    def _build_dataset_zip_bytes():
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('data.yaml', 'path: .\ntrain: images/train\nval: images/val\n')
            archive.writestr('images/train/.keep', '')
            archive.writestr('images/val/.keep', '')
            archive.writestr('labels/train/.keep', '')
            archive.writestr('labels/val/.keep', '')
        payload.seek(0)
        return payload

    @staticmethod
    def _build_nested_dataset_zip_bytes():
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('nested/dataset/data.yaml', 'path: .\ntrain: images/train\nval: images/val\n')
            archive.writestr('nested/dataset/images/train/.keep', '')
            archive.writestr('nested/dataset/images/val/.keep', '')
            archive.writestr('nested/dataset/labels/train/.keep', '')
            archive.writestr('nested/dataset/labels/val/.keep', '')
        payload.seek(0)
        return payload

    @patch('api.train_api.threading.Thread')
    def test_start_and_status_endpoints_work_together(self, mock_thread_cls):
        mock_thread = mock_thread_cls.return_value
        mock_thread.start.return_value = None

        dataset_zip = self._build_dataset_zip_bytes()
        response = self.client.post(
            '/api/train/start',
            data={
                'dataset_zip': (dataset_zip, 'dataset.zip'),
                'data_yaml': 'data.yaml',
                'epochs': '5',
                'batch': '2',
                'imgsz': '320',
                'device': 'cpu',
                'resume': 'false',
                'run_name': 'unit-train',
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertIn('job_id', payload)

        job_id = payload['job_id']

        status_response = self.client.get(f'/api/train/status/{job_id}')
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.get_json()
        self.assertTrue(status_payload.get('ok'))
        self.assertEqual(status_payload['job']['job_id'], job_id)

        active_response = self.client.get('/api/train/status')
        self.assertEqual(active_response.status_code, 200)
        active_payload = active_response.get_json()
        self.assertTrue(active_payload.get('ok'))
        self.assertEqual(active_payload['job']['job_id'], job_id)

    def test_train_config_endpoint_returns_limits(self):
        response = self.client.get('/api/train/config')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload['limits']['train_max_content_length'], self.app.config['TRAIN_MAX_CONTENT_LENGTH'])
        self.assertIn('zip', payload['accept']['dataset_extensions'])

    @patch('api.train_api.threading.Thread')
    def test_start_training_auto_detects_nested_data_yaml(self, mock_thread_cls):
        mock_thread = mock_thread_cls.return_value
        mock_thread.start.return_value = None

        dataset_zip = self._build_nested_dataset_zip_bytes()
        response = self.client.post(
            '/api/train/start',
            data={
                'dataset_zip': (dataset_zip, 'dataset.zip'),
                'data_yaml': 'data.yaml',
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get('ok'))

        job_id = payload['job_id']
        status_response = self.client.get(f'/api/train/status/{job_id}')
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.get_json()
        self.assertTrue(status_payload.get('ok'))
        self.assertEqual(status_payload['job']['meta']['yaml_relative'], 'nested/dataset/data.yaml')

    @patch('api.train_api.threading.Thread')
    def test_active_status_falls_back_to_latest_job(self, mock_thread_cls):
        mock_thread = mock_thread_cls.return_value
        mock_thread.start.return_value = None

        dataset_zip = self._build_dataset_zip_bytes()
        response = self.client.post(
            '/api/train/start',
            data={
                'dataset_zip': (dataset_zip, 'dataset.zip'),
                'data_yaml': 'data.yaml',
            },
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        job_id = payload['job_id']

        with _job_lock:
            _job_state['active_job_id'] = None

        active_response = self.client.get('/api/train/status')
        self.assertEqual(active_response.status_code, 200)
        active_payload = active_response.get_json()
        self.assertTrue(active_payload.get('ok'))
        self.assertEqual(active_payload['job']['job_id'], job_id)

    def _start_job(self):
        response = self.client.post(
            '/api/train/start',
            data={
                'dataset_zip': (self._build_dataset_zip_bytes(), 'dataset.zip'),
                'data_yaml': 'data.yaml',
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()['job_id']

    @patch('api.train_api.threading.Thread')
    def test_started_job_is_persisted(self, _mock_thread_cls):
        job_id = self._start_job()

        with self.app.app_context():
            row = db.session.get(TrainJob, job_id)
            self.assertIsNotNone(row)
            self.assertEqual(row.status, 'queued')
            self.assertIn('data.yaml', row.meta_json)

    @patch('api.train_api.threading.Thread')
    def test_status_survives_restart(self, _mock_thread_cls):
        job_id = self._start_job()

        # Simulate a process restart: in-memory state is gone, database remains.
        self._reset_jobs()

        status_response = self.client.get(f'/api/train/status/{job_id}')
        self.assertEqual(status_response.status_code, 200)
        job = status_response.get_json()['job']
        self.assertEqual(job['job_id'], job_id)
        self.assertEqual(job['status'], 'queued')
        self.assertFalse(job['is_active'])

        active_response = self.client.get('/api/train/status')
        self.assertEqual(active_response.get_json()['job']['job_id'], job_id)

    @patch('api.train_api.threading.Thread')
    def test_start_requires_admin(self, mock_thread_cls):
        self._login_as(None)
        anonymous = self.client.post(
            '/api/train/start',
            data={'dataset_zip': (self._build_dataset_zip_bytes(), 'dataset.zip')},
            content_type='multipart/form-data',
        )
        self.assertEqual(anonymous.status_code, 401)

        self._login_as(self.member_id)
        member = self.client.post(
            '/api/train/start',
            data={'dataset_zip': (self._build_dataset_zip_bytes(), 'dataset.zip')},
            content_type='multipart/form-data',
        )
        self.assertEqual(member.status_code, 403)
        mock_thread_cls.assert_not_called()

    def test_status_and_config_require_login(self):
        self._login_as(None)
        for url in ('/api/train/status', '/api/train/status/abc', '/api/train/config'):
            self.assertEqual(self.client.get(url).status_code, 401, url)

        self._login_as(self.member_id)
        self.assertEqual(self.client.get('/api/train/status').status_code, 200)

    def test_unknown_job_returns_404(self):
        response = self.client.get('/api/train/status/does-not-exist')
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
