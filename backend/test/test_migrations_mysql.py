"""Migration tests against a real MySQL server.

Skipped unless MYSQL_TEST_URL is set, e.g.
    MYSQL_TEST_URL=mysql+pymysql://root:root@127.0.0.1:3306/trashdet_test
The database named in the URL is dropped and recreated by every test.
CI runs these in the `backend-mysql` job.
"""
import os
import unittest

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate, stamp, upgrade

import database.models  # noqa: F401  (register all models on db.metadata)
from app_factory_services import apply_database_migrations_impl, ensure_ownership_schema_impl
from database.db import db

MYSQL_TEST_URL = os.getenv('MYSQL_TEST_URL', '')
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_SQL_PATH = os.path.join(BACKEND_DIR, 'test', 'fixtures', 'legacy_database.sql')

# Structural differences that must not exist between migrated schema and models.
STRUCTURAL_DIFFS = {'add_table', 'remove_table', 'add_column', 'remove_column', 'add_fk', 'remove_fk', 'add_index', 'remove_index'}


@unittest.skipUnless(MYSQL_TEST_URL, 'MYSQL_TEST_URL not set')
class MysqlMigrationsTestCase(unittest.TestCase):
    def setUp(self):
        url = sa.engine.make_url(MYSQL_TEST_URL)
        server_engine = sa.create_engine(url.set(database=''))
        with server_engine.begin() as connection:
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS `{url.database}`'))
            connection.execute(sa.text(f'CREATE DATABASE `{url.database}` CHARACTER SET utf8mb4'))
        server_engine.dispose()

        self.app = Flask(__name__)
        self.app.config.update({
            'SQLALCHEMY_DATABASE_URI': MYSQL_TEST_URL,
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        Migrate(self.app, db, directory=os.path.join(BACKEND_DIR, 'migrations'))
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    # --- helpers ---

    def _sql(self, statement, **params):
        with db.engine.begin() as connection:
            return connection.execute(sa.text(statement), params)

    def _scalar(self, statement, **params):
        with db.engine.connect() as connection:
            return connection.execute(sa.text(statement), params).scalar()

    def _column_type(self, table, column):
        return self._scalar(
            'SELECT DATA_TYPE FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c',
            t=table, c=column,
        )

    def _foreign_key(self, table, column):
        inspector = sa.inspect(db.engine)
        matches = [fk for fk in inspector.get_foreign_keys(table) if fk['constrained_columns'] == [column]]
        self.assertEqual(len(matches), 1, f'{table}.{column} should have exactly one foreign key: {matches}')
        return matches[0]

    def _assert_final_schema(self, check_indexes=True):
        diff = compare_metadata(MigrationContext.configure(db.engine.connect()), db.metadata)
        structural = [item for item in diff if isinstance(item, tuple) and item[0] in STRUCTURAL_DIFFS]
        # database.sql had extra columns/indexes the models never used; only missing things matter.
        missing = [item for item in structural if item[0].startswith('add_')]
        if not check_indexes:
            # database.sql created equivalent indexes under its own names.
            missing = [item for item in missing if item[0] != 'add_index']
        self.assertEqual(missing, [], f'Schema is missing objects defined by the models: {missing}')

        for table, column in [('detection_tasks', 'latitude'), ('robots', 'current_lat'), ('robots', 'target_lng')]:
            self.assertEqual(self._column_type(table, column), 'double')

        item_fk = self._foreign_key('detection_items', 'task_id')
        self.assertEqual(item_fk['referred_table'], 'detection_tasks')
        self.assertEqual(item_fk['options'].get('ondelete'), 'CASCADE')
        for table, column in [('detection_tasks', 'user_id'), ('robots', 'owner_user_id'),
                              ('robot_patrol_tasks', 'created_by_user_id'), ('operation_logs', 'user_id')]:
            fk = self._foreign_key(table, column)
            self.assertEqual(fk['referred_table'], 'users')
            self.assertEqual(fk['options'].get('ondelete'), 'SET NULL')

    def _assert_delete_behaviour(self):
        self._sql("INSERT INTO users (id, username, password_hash, security_code, role) VALUES (50, 'gone', 'x', 'x', 'user')")
        self._sql("INSERT INTO robots (id, device_id, name, status, owner_user_id, current_lat, next_command, battery) "
                  "VALUES (50, 'dev-50', 'r', 'OFFLINE', 50, 120.123456, 'IDLE', 100)")
        self._sql("INSERT INTO detection_tasks (id, source_path, status, user_id, latitude) VALUES (50, 'a.jpg', 'DONE', 50, 30.987654)")
        self._sql("INSERT INTO detection_items (id, task_id, label, handle_state) VALUES (50, 50, 'bottle', 'NEW')")

        self.assertAlmostEqual(self._scalar('SELECT current_lat FROM robots WHERE id = 50'), 120.123456, places=6)
        self.assertAlmostEqual(self._scalar('SELECT latitude FROM detection_tasks WHERE id = 50'), 30.987654, places=6)

        self._sql('DELETE FROM users WHERE id = 50')
        self.assertIsNone(self._scalar('SELECT owner_user_id FROM robots WHERE id = 50'))
        self.assertIsNone(self._scalar('SELECT user_id FROM detection_tasks WHERE id = 50'))

        self._sql('DELETE FROM detection_tasks WHERE id = 50')
        self.assertEqual(self._scalar('SELECT COUNT(*) FROM detection_items WHERE id = 50'), 0)

    # --- tests ---

    def test_fresh_database(self):
        upgrade()
        self._assert_final_schema()
        self._assert_delete_behaviour()

    def test_database_created_by_old_app_code(self):
        # Tables as db.create_all() used to create them (= migrations 0001 + 0002), with bad rows.
        upgrade(revision='0002')
        self._sql("INSERT INTO users (id, username, password_hash, security_code, role) VALUES (1, 'admin', 'x', 'x', NULL)")
        self._sql("INSERT INTO robots (id, device_id, owner_user_id) VALUES (1, 'dev-1', 999)")
        self._sql("INSERT INTO detection_tasks (id, source_path, user_id) VALUES (1, 'a.jpg', 999)")
        self._sql("INSERT INTO detection_items (id, task_id, label) VALUES (1, NULL, 'orphan'), (2, 1, 'kept')")
        self._sql("INSERT INTO operation_logs (id, user_id, action) VALUES (1, 999, 'x')")

        upgrade()

        self._assert_final_schema()
        self.assertEqual(self._scalar('SELECT role FROM users WHERE id = 1'), 'user')
        self.assertIsNone(self._scalar('SELECT owner_user_id FROM robots WHERE id = 1'))
        self.assertIsNone(self._scalar('SELECT user_id FROM detection_tasks WHERE id = 1'))
        self.assertIsNone(self._scalar('SELECT user_id FROM operation_logs WHERE id = 1'))
        self.assertEqual(self._scalar('SELECT COUNT(*) FROM detection_items'), 1)
        self._assert_delete_behaviour()

    def test_database_created_from_legacy_sql(self):
        with open(LEGACY_SQL_PATH, encoding='utf-8') as fp:
            script = '\n'.join(line for line in fp if not line.lstrip().startswith('--'))
        for statement in filter(None, (part.strip() for part in script.split(';'))):
            self._sql(statement)
        self._sql("INSERT INTO users (id, username, password_hash, security_code) VALUES (1, 'admin', 'x', 'x')")
        self._sql("INSERT INTO robots (id, device_id, owner_user_id, current_lat) VALUES (1, 'dev-1', 1, 30.5)")

        # Same path the app takes at startup for a database without alembic_version.
        apply_database_migrations_impl(
            db,
            upgrade_func=upgrade,
            stamp_func=stamp,
            ensure_legacy_schema=lambda: ensure_ownership_schema_impl(self.app, db),
        )

        self.assertEqual(self._scalar('SELECT version_num FROM alembic_version'), '0003')
        self._assert_final_schema(check_indexes=False)
        self.assertEqual(self._scalar('SELECT owner_user_id FROM robots WHERE id = 1'), 1)
        self._assert_delete_behaviour()


if __name__ == '__main__':
    unittest.main()
