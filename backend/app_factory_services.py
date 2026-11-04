import logging
import os
import random
import secrets
from datetime import datetime
from logging.handlers import RotatingFileHandler

from flask import jsonify, request
from sqlalchemy import inspect, text
from werkzeug.exceptions import HTTPException


def seed_random_state(seed=42, np_module=None, torch_module=None):
    random.seed(seed)
    if np_module is not None:
        np_module.random.seed(seed)
    if torch_module is not None:
        torch_module.manual_seed(seed)
        if torch_module.cuda.is_available():
            torch_module.cuda.manual_seed(seed)
            torch_module.cuda.manual_seed_all(seed)


def ensure_bootstrap_admin_impl(app, db_obj, user_model, os_module=os, logger=None):
    if app.config.get('TESTING'):
        return

    logger_obj = logger or logging.getLogger(__name__)
    try:
        has_user = db_obj.session.query(user_model.id).first() is not None
        if has_user:
            return

        username = os_module.getenv('TRASHDET_ADMIN_USERNAME', 'admin').strip() or 'admin'
        password = os_module.getenv('TRASHDET_ADMIN_PASSWORD', '').strip()
        security_code = os_module.getenv('TRASHDET_ADMIN_SECURITY_CODE', '').strip()
        generated = []
        if not password:
            password = secrets.token_urlsafe(12)
            generated.append(f'password={password}')
        if not security_code:
            security_code = f'{secrets.randbelow(10 ** 6):06d}'
            generated.append(f'security_code={security_code}')

        admin_user = user_model(username=username, role='admin')
        admin_user.set_password(password)
        admin_user.set_security_code(security_code)
        db_obj.session.add(admin_user)
        db_obj.session.commit()

        logger_obj.warning(
            'No users detected. Bootstrap admin account created. '
            'Please change credentials immediately. username=%s',
            username,
        )
        if generated:
            # Printed once so the operator can log in; set TRASHDET_ADMIN_* to choose them instead.
            logger_obj.warning('Generated bootstrap admin credentials: %s', ' '.join(generated))
    except Exception:
        db_obj.session.rollback()
        logger_obj.exception('Failed to create bootstrap admin account.')


def ensure_ownership_schema_impl(app, db_obj, logger=None):
    logger_obj = logger or logging.getLogger(__name__)

    try:
        inspector = inspect(db_obj.engine)
        table_names = set(inspector.get_table_names())

        def _pick_table_name(*candidates):
            for candidate in candidates:
                if candidate in table_names:
                    return candidate
            return None

        users_table = _pick_table_name('users', 'user')
        tasks_table = _pick_table_name('detection_tasks', 'detect_task')
        robots_table = _pick_table_name('robots', 'robot')
        patrol_tasks_table = _pick_table_name('robot_patrol_tasks', 'robot_patrol_task')

        if not users_table or not tasks_table or not robots_table:
            return

        table_column_names = {
            users_table: {column['name'] for column in inspector.get_columns(users_table)},
            tasks_table: {column['name'] for column in inspector.get_columns(tasks_table)},
            robots_table: {column['name'] for column in inspector.get_columns(robots_table)},
        }
        table_index_names = {
            tasks_table: {index['name'] for index in inspector.get_indexes(tasks_table)},
            robots_table: {index['name'] for index in inspector.get_indexes(robots_table)},
        }

        ddl_statements = []
        if 'organization' not in table_column_names[users_table]:
            ddl_statements.append(f'ALTER TABLE `{users_table}` ADD COLUMN organization VARCHAR(120)')
        if 'user_id' not in table_column_names[tasks_table]:
            ddl_statements.append(f'ALTER TABLE `{tasks_table}` ADD COLUMN user_id INTEGER')
        if 'owner_user_id' not in table_column_names[robots_table]:
            ddl_statements.append(f'ALTER TABLE `{robots_table}` ADD COLUMN owner_user_id INTEGER')
        if patrol_tasks_table:
            robot_patrol_columns = {column['name'] for column in inspector.get_columns(patrol_tasks_table)}
            if 'current_waypoint_index' not in robot_patrol_columns:
                ddl_statements.append(
                    f'ALTER TABLE `{patrol_tasks_table}` ADD COLUMN current_waypoint_index INTEGER NOT NULL DEFAULT 0'
                )

        detect_task_user_index_names = {'idx_detect_task_user_id', 'idx_detection_tasks_user_id'}
        robot_owner_index_names = {'idx_robot_owner_user_id', 'idx_robots_owner_user_id'}

        if not (table_index_names[tasks_table] & detect_task_user_index_names):
            ddl_statements.append(f'CREATE INDEX idx_detection_tasks_user_id ON `{tasks_table}` (user_id)')
        if not (table_index_names[robots_table] & robot_owner_index_names):
            ddl_statements.append(f'CREATE INDEX idx_robots_owner_user_id ON `{robots_table}` (owner_user_id)')

        if not ddl_statements:
            return

        for statement in ddl_statements:
            db_obj.session.execute(text(statement))
        db_obj.session.commit()
        logger_obj.info('Ownership schema patch applied. statements=%s', len(ddl_statements))
    except Exception:
        db_obj.session.rollback()
        logger_obj.exception('Failed to patch ownership schema.')


def apply_database_migrations_impl(db_obj, upgrade_func, stamp_func, ensure_legacy_schema, logger=None):
    """Bring the database schema up to date with Alembic migrations.

    Databases created before migrations existed (by db.create_all() or
    database/database.sql) have tables but no alembic_version table. They are
    patched with the legacy column fixes, stamped at the matching baseline
    revision, and then upgraded normally.
    """
    logger_obj = logger or logging.getLogger(__name__)
    table_names = set(inspect(db_obj.engine).get_table_names())

    if 'alembic_version' not in table_names and 'users' in table_names:
        ensure_legacy_schema()
        baseline = '0002' if 'train_jobs' in table_names else '0001'
        stamp_func(revision=baseline)
        logger_obj.warning('Existing database adopted by migrations at revision %s.', baseline)

    upgrade_func()


INTERRUPTED_MESSAGE = '服务重启，任务已中断，请重新提交。'


def recover_interrupted_jobs_impl(db_obj, detect_task_model, train_job_model, logger=None):
    """Mark jobs left unfinished by a previous process as failed.

    Background work runs in threads of a single process, so anything still
    pending at startup can never finish. Run the app with a single worker.
    """
    logger_obj = logger or logging.getLogger(__name__)
    try:
        stale_tasks = detect_task_model.query.filter(detect_task_model.status == 'PENDING').all()
        for task in stale_tasks:
            task.status = 'FAILED'
            task.error_msg = INTERRUPTED_MESSAGE

        stale_jobs = train_job_model.query.filter(train_job_model.status.in_(('queued', 'running'))).all()
        now_iso = datetime.now().isoformat(timespec='seconds')
        for job in stale_jobs:
            job.status = 'failed'
            job.error = INTERRUPTED_MESSAGE
            job.completed_at = now_iso

        if stale_tasks or stale_jobs:
            db_obj.session.commit()
            logger_obj.warning(
                'Marked interrupted jobs as failed. detect_tasks=%s train_jobs=%s',
                len(stale_tasks),
                len(stale_jobs),
            )
    except Exception:
        db_obj.session.rollback()
        logger_obj.exception('Failed to recover interrupted jobs.')


def mask_database_uri(database_uri):
    if not database_uri:
        return 'unknown'
    if '://' not in database_uri or '@' not in database_uri:
        return database_uri

    scheme, remainder = database_uri.split('://', 1)
    credentials, suffix = remainder.split('@', 1)
    if ':' not in credentials:
        return f'{scheme}://***@{suffix}'

    username, _ = credentials.split(':', 1)
    return f'{scheme}://{username}:***@{suffix}'


def configure_root_logging(app, rotating_file_handler_cls=RotatingFileHandler):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    os.makedirs(app.config.get('LOG_DIR', 'logs'), exist_ok=True)
    log_path = os.path.join(app.config.get('LOG_DIR', 'logs'), 'service.log')
    root_logger = logging.getLogger()
    has_file_handler = any(
        isinstance(handler, rotating_file_handler_cls) and getattr(handler, 'baseFilename', '') == os.path.abspath(log_path)
        for handler in root_logger.handlers
    )
    if has_file_handler:
        return

    file_handler = rotating_file_handler_cls(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    root_logger.addHandler(file_handler)


def register_blueprints(app, blueprint_specs):
    for blueprint, url_prefix in blueprint_specs:
        if url_prefix:
            app.register_blueprint(blueprint, url_prefix=url_prefix)
        else:
            app.register_blueprint(blueprint)


def register_error_handler(app):
    @app.errorhandler(Exception)
    def render_error(error):
        if request.path.startswith('/api'):
            if isinstance(error, HTTPException):
                message = error.description
                if error.code == 413 and request.path.startswith('/api/train'):
                    train_max_content_length = app.config.get('TRAIN_MAX_CONTENT_LENGTH')
                    if isinstance(train_max_content_length, int) and train_max_content_length > 0:
                        limit_mb = round(train_max_content_length / (1024 * 1024), 2)
                        message = f'训练数据包过大，当前上限为 {limit_mb} MB。'
                    else:
                        message = '训练数据包过大，请压缩数据集后重试。'

                return jsonify({
                    'ok': False,
                    'code': error.code,
                    'name': error.name,
                    'message': message,
                }), error.code

            logging.exception('An error occurred during an API request.')
            return jsonify({
                'ok': False,
                'code': 500,
                'name': 'Internal Server Error',
                'message': str(error) if app.debug else 'An unexpected error occurred.'
            }), 500

        if isinstance(error, HTTPException):
            return error

        logging.exception('An error occurred during a web request.')
        return 'Internal Server Error', 500


def register_health_route(app):
    @app.route('/health')
    def show_health():
        return jsonify({'status': 'ok', 'version': '2.0.0'})
