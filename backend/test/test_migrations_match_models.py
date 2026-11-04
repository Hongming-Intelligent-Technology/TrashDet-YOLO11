import os
import tempfile
import unittest

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import Migrate, upgrade

import database.models  # noqa: F401  (register all models on db.metadata)
from database.db import db

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MigrationsMatchModelsTestCase(unittest.TestCase):
    """Applying all migrations to an empty database must produce the schema the models describe."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config.update({
            'SQLALCHEMY_DATABASE_URI': f"sqlite:///{os.path.join(self.temp_dir.name, 'migrations.db')}",
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        Migrate(self.app, db, directory=os.path.join(BACKEND_DIR, 'migrations'))

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def test_upgrade_head_matches_models(self):
        with self.app.app_context():
            upgrade()
            with db.engine.connect() as connection:
                diff = compare_metadata(MigrationContext.configure(connection), db.metadata)
        self.assertEqual(diff, [], f'Migrations are out of sync with models: {diff}')


if __name__ == '__main__':
    unittest.main()
