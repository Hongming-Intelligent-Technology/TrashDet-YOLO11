import unittest

from flask import Flask

from app_factory_services import INTERRUPTED_MESSAGE, recover_interrupted_jobs_impl
from database.db import db
from database.models import DetectTask, TrainJob


class JobRecoveryTestCase(unittest.TestCase):
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

    def test_marks_unfinished_jobs_as_failed(self):
        with self.app.app_context():
            pending = DetectTask(source_path='static/uploads/a.mp4', source_type='video', status='PENDING')
            done = DetectTask(source_path='static/uploads/b.jpg', source_type='image', status='DONE')
            db.session.add_all([
                pending,
                done,
                TrainJob(id='running1', status='running', created_at='2026-01-01T00:00:00'),
                TrainJob(id='queued1', status='queued', created_at='2026-01-01T00:00:01'),
                TrainJob(id='completed1', status='completed', created_at='2026-01-01T00:00:02'),
            ])
            db.session.commit()
            pending_id, done_id = pending.id, done.id

            recover_interrupted_jobs_impl(db, DetectTask, TrainJob)

            self.assertEqual(db.session.get(DetectTask, pending_id).status, 'FAILED')
            self.assertEqual(db.session.get(DetectTask, pending_id).error_msg, INTERRUPTED_MESSAGE)
            self.assertEqual(db.session.get(DetectTask, done_id).status, 'DONE')
            self.assertEqual(db.session.get(TrainJob, 'running1').status, 'failed')
            self.assertEqual(db.session.get(TrainJob, 'queued1').status, 'failed')
            self.assertIsNotNone(db.session.get(TrainJob, 'queued1').completed_at)
            self.assertEqual(db.session.get(TrainJob, 'completed1').status, 'completed')

    def test_no_unfinished_jobs_is_a_no_op(self):
        with self.app.app_context():
            recover_interrupted_jobs_impl(db, DetectTask, TrainJob)
            self.assertEqual(TrainJob.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
