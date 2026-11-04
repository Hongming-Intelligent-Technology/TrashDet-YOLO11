import unittest
from datetime import datetime

from flask import Flask

from database.db import db
from database.models import DetectTask, User


class ModelsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def test_user_password_and_security_code(self):
        user = User(username='u1', role='user')
        user.set_password('pass123')
        user.set_security_code('code123')
        self.assertTrue(user.check_password('pass123'))
        self.assertFalse(user.check_password('wrong'))
        self.assertTrue(user.check_security_code('code123'))
        self.assertFalse(user.check_security_code('bad'))

    def test_detect_task_to_dict(self):
        created = datetime.now()
        task = DetectTask(
            source_type='image',
            source_path='a.jpg',
            result_path='b.jpg',
            device_id='R1',
            location='x',
            status='DONE',
            latitude=1.2,
            longitude=3.4,
            created_at=created,
        )
        result = task.to_dict()
        self.assertEqual(result['source_type'], 'image')
        self.assertEqual(result['device_id'], 'R1')
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(result['latitude'], 1.2)
        self.assertTrue(result['created_at'])


if __name__ == '__main__':
    unittest.main()
