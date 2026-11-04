import unittest

from flask import Flask

from database.db import db
from database.models import DetectItem, DetectTask, Robot


class ModelConstraintsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()

    def test_long_strings_are_cut_to_column_length_on_insert(self):
        task = DetectTask(source_path='a.jpg', location='地' * 400, device_id='d' * 80, source_type='parser-' * 10)
        db.session.add(task)
        db.session.commit()

        db.session.refresh(task)
        self.assertEqual(len(task.location), 255)
        self.assertEqual(len(task.device_id), 50)
        self.assertEqual(len(task.source_type), 20)

    def test_long_strings_are_cut_on_update(self):
        robot = Robot(device_id='dev-1', name='r')
        db.session.add(robot)
        db.session.commit()

        robot.next_command = 'X' * 500
        db.session.commit()
        db.session.refresh(robot)
        self.assertEqual(len(robot.next_command), 100)

    def test_short_strings_and_text_are_unchanged(self):
        task = DetectTask(source_path='a.jpg', location='校园北门', error_msg='e' * 5000)
        db.session.add(task)
        db.session.commit()
        db.session.refresh(task)
        self.assertEqual(task.location, '校园北门')
        self.assertEqual(len(task.error_msg), 5000)

    def test_deleting_task_through_orm_deletes_its_items(self):
        task = DetectTask(source_path='a.jpg')
        db.session.add(task)
        db.session.commit()
        db.session.add(DetectItem(task_id=task.id, label='bottle'))
        db.session.commit()

        db.session.delete(task)
        db.session.commit()
        self.assertEqual(DetectItem.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
