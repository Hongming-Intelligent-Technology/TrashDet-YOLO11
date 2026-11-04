import unittest

from flask import Flask
from sqlalchemy import text

from app_factory_services import apply_database_migrations_impl
from database.db import db


class ApplyDatabaseMigrationsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        self.calls = []

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def _run(self):
        apply_database_migrations_impl(
            db,
            upgrade_func=lambda: self.calls.append('upgrade'),
            stamp_func=lambda revision: self.calls.append(f'stamp:{revision}'),
            ensure_legacy_schema=lambda: self.calls.append('legacy'),
        )

    def _create_tables(self, *names):
        for name in names:
            db.session.execute(text(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY)'))
        db.session.commit()

    def test_empty_database_is_only_upgraded(self):
        with self.app.app_context():
            self._run()
        self.assertEqual(self.calls, ['upgrade'])

    def test_legacy_database_is_patched_stamped_and_upgraded(self):
        with self.app.app_context():
            self._create_tables('users', 'detection_tasks', 'robots')
            self._run()
        self.assertEqual(self.calls, ['legacy', 'stamp:0001', 'upgrade'])

    def test_legacy_database_with_train_jobs_is_stamped_at_0002(self):
        with self.app.app_context():
            self._create_tables('users', 'train_jobs')
            self._run()
        self.assertEqual(self.calls, ['legacy', 'stamp:0002', 'upgrade'])

    def test_already_migrated_database_is_only_upgraded(self):
        with self.app.app_context():
            self._create_tables('users', 'alembic_version')
            self._run()
        self.assertEqual(self.calls, ['upgrade'])


if __name__ == '__main__':
    unittest.main()
