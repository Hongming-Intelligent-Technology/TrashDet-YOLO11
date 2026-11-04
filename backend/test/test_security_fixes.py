import logging
import os
import tempfile
import unittest
from types import SimpleNamespace

from flask import Flask

from app_factory_services import ensure_bootstrap_admin_impl
from database.db import db
from database.models import User
from web.helpers import _delete_task_files, _resolve_deletable_path


class DeletableTaskFilesTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = self.temp_dir.name
        self.app = Flask(__name__, root_path=root)
        self.app.config['STATIC_DIR'] = os.path.join(root, 'static')
        os.makedirs(os.path.join(root, 'static', 'uploads'))
        self.inside = os.path.join(root, 'static', 'uploads', 'a.jpg')
        self.outside = os.path.join(root, 'secret.txt')
        for path in (self.inside, self.outside):
            with open(path, 'w', encoding='utf-8') as fp:
                fp.write('x')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_only_paths_inside_static_are_deletable(self):
        with self.app.app_context():
            self.assertEqual(_resolve_deletable_path('static/uploads/a.jpg'), os.path.realpath(self.inside))
            for path in ('../secret.txt', 'secret.txt', 'static/../secret.txt', self.outside, '', None, 'ingest://abc'):
                self.assertIsNone(_resolve_deletable_path(path), path)

    def test_delete_task_files_never_touches_files_outside_static(self):
        task = SimpleNamespace(source_path='static/uploads/a.jpg', result_path=self.outside)
        with self.app.app_context():
            _delete_task_files(task)
        self.assertFalse(os.path.exists(self.inside))
        self.assertTrue(os.path.exists(self.outside))


class BootstrapAdminTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
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

    def _bootstrap(self, env):
        os_stub = SimpleNamespace(getenv=lambda name, default=None: env.get(name, default))
        with self.assertLogs('bootstrap-test', level=logging.WARNING) as logs:
            ensure_bootstrap_admin_impl(self.app, db, User, os_module=os_stub, logger=logging.getLogger('bootstrap-test'))
        return '\n'.join(logs.output)

    def test_generates_random_credentials_when_not_configured(self):
        output = self._bootstrap({})
        admin = User.query.filter_by(username='admin').one()
        self.assertEqual(admin.role, 'admin')
        self.assertFalse(admin.check_password('admin123456'))

        password = output.split('password=')[1].split()[0]
        code = output.split('security_code=')[1].split()[0]
        self.assertTrue(admin.check_password(password))
        self.assertTrue(admin.check_security_code(code))

    def test_uses_configured_credentials(self):
        output = self._bootstrap({
            'TRASHDET_ADMIN_USERNAME': 'root',
            'TRASHDET_ADMIN_PASSWORD': 'chosen-password',
            'TRASHDET_ADMIN_SECURITY_CODE': '4321',
        })
        admin = User.query.filter_by(username='root').one()
        self.assertTrue(admin.check_password('chosen-password'))
        self.assertNotIn('chosen-password', output)


if __name__ == '__main__':
    unittest.main()
