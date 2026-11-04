import io
import os
import unittest
from unittest.mock import patch

from flask import Flask

from api.detect_api import detect_bp
from database.db import db
from database.models import DetectItem, DetectTask


class _FakeDetector:
    def analyze_uploaded_waste_image(self, source_path, save_result=False, result_path=None, conf_thres=0.25):
        return [
            {
                'label': 'Plastic',
                'confidence': 0.93,
                'bbox': [10, 10, 50, 50],
            }
        ]


class _FakeEmptyDetector:
    def analyze_uploaded_waste_image(self, source_path, save_result=False, result_path=None, conf_thres=0.25):
        return []


class DetectApiRoutesTestCase(unittest.TestCase):
    def setUp(self):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static_dir = os.path.join(backend_dir, 'static')
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'UPLOAD_DIR': os.path.join(static_dir, 'uploads'),
            'RESULT_DIR': os.path.join(static_dir, 'results'),
            'ALLOWED_EXTENSIONS': {'png', 'jpg', 'jpeg'},
            'YOLO_CONF_THRESHOLD': 0.25,
        })

        db.init_app(self.app)
        self.app.register_blueprint(detect_bp, url_prefix='/api')

        with self.app.app_context():
            db.create_all()

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    @patch('api.detect_api.ensure_storage_dirs')
    @patch('api.detect_api.resolve_location', return_value='测试地点')
    @patch('api.detect_api.save_uploaded_file', return_value=('x.jpg', '/tmp/x.jpg', 'static/uploads/x.jpg'))
    @patch('api.detect_api.load_detector', return_value=_FakeDetector())
    @patch('api.detect_api.cv2.imwrite', return_value=True)
    def test_detect_image_success(self, *_mocks):
        data = {
            'image': (io.BytesIO(b'fake-image-data'), 'sample.jpg'),
            'latitude': '30.11',
            'longitude': '110.22',
        }
        resp = self.client.post('/api/detect', data=data, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 200)

        payload = resp.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload.get('status'), 'success')
        self.assertIn('result', payload)
        self.assertIn('task', payload)

        with self.app.app_context():
            self.assertEqual(DetectTask.query.count(), 1)

    @patch('api.detect_api.ensure_storage_dirs')
    @patch('api.detect_api.resolve_location', return_value='测试地点')
    @patch('api.detect_api.save_uploaded_file', return_value=('x.jpg', '/tmp/x.jpg', 'static/uploads/x.jpg'))
    @patch('api.detect_api.load_detector', return_value=_FakeEmptyDetector())
    @patch('api.detect_api.cv2.imwrite', return_value=True)
    def test_detect_image_empty_result_not_recorded(self, *_mocks):
        data = {
            'image': (io.BytesIO(b'fake-image-data'), 'sample.jpg'),
            'latitude': '30.11',
            'longitude': '110.22',
        }
        resp = self.client.post('/api/detect', data=data, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 200)

        payload = resp.get_json()
        self.assertTrue(payload.get('ok'))
        self.assertEqual(payload.get('result'), [])
        self.assertEqual(payload.get('recorded'), False)
        self.assertIsNone(payload.get('task'))

        with self.app.app_context():
            self.assertEqual(DetectTask.query.count(), 0)
            self.assertEqual(DetectItem.query.count(), 0)

    @patch('api.detect_api.save_uploaded_file')
    def test_detect_image_rejects_oversized_upload_before_saving(self, mock_save):
        self.app.config['IMAGE_MAX_CONTENT_LENGTH'] = 1024
        data = {'image': (io.BytesIO(b'x' * (200 * 1024)), 'big.jpg')}
        resp = self.client.post('/api/detect', data=data, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 413)
        self.assertFalse(resp.get_json().get('ok'))
        mock_save.assert_not_called()

    def test_detect_image_missing_file(self):
        resp = self.client.post('/api/detect', data={}, content_type='multipart/form-data')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json().get('ok'))

    def test_detect_ingest_success(self):
        payload = {
            'source_type': 'parser',
            'device_id': 'cam-01',
            'latitude': 30.123,
            'longitude': 110.456,
            'location': '测试街道',
            'source_path': 'ingest://sample-001',
            'detections': [
                {'label': 'Plastic', 'confidence': 0.95, 'bbox': [10, 20, 120, 150]},
                {'class_name': 'Paper', 'score': 0.66, 'x1': 5, 'y1': 6, 'x2': 30, 'y2': 44},
            ],
        }
        resp = self.client.post('/api/detect/ingest', json=payload)
        self.assertEqual(resp.status_code, 200)

        body = resp.get_json()
        self.assertTrue(body.get('ok'))
        self.assertEqual(body.get('inserted_items'), 2)

        with self.app.app_context():
            self.assertEqual(DetectTask.query.count(), 1)
            self.assertEqual(DetectItem.query.count(), 2)

    def test_detect_ingest_empty_result_not_recorded(self):
        payload = {
            'source_type': 'parser',
            'device_id': 'cam-01',
            'latitude': 30.123,
            'longitude': 110.456,
            'location': '测试街道',
            'source_path': 'ingest://sample-002',
            'detections': [],
        }
        resp = self.client.post('/api/detect/ingest', json=payload)
        self.assertEqual(resp.status_code, 200)

        body = resp.get_json()
        self.assertTrue(body.get('ok'))
        self.assertEqual(body.get('inserted_items'), 0)
        self.assertEqual(body.get('recorded'), False)
        self.assertIsNone(body.get('task_id'))
        self.assertIsNone(body.get('task'))

        with self.app.app_context():
            self.assertEqual(DetectTask.query.count(), 0)
            self.assertEqual(DetectItem.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
