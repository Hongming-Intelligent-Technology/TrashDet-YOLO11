import logging
import os
import random

try:
    import numpy as np
except ImportError:
    np = None

try:
    import torch
except ImportError:
    torch = None
except OSError:
    # Handle Windows DLL dependency issues (e.g. missing VC++ runtime) gracefully.
    torch = None
    logging.warning("PyTorch import failed due to missing DLL dependencies. Seeding skips torch.")

from flask import Flask
from flask_migrate import Migrate, stamp as migrate_stamp, upgrade as migrate_upgrade
from api.detect_helpers import log_detection_dependency_report
from app_factory_services import (
    apply_database_migrations_impl,
    configure_root_logging,
    ensure_bootstrap_admin_impl,
    ensure_ownership_schema_impl,
    mask_database_uri,
    recover_interrupted_jobs_impl,
    register_blueprints,
    register_error_handler,
    register_health_route,
    seed_random_state,
)
from config import Config, load_yaml_runtime_overrides
from database.db import db
from database.models import DetectTask, TrainJob, User
from api.detect_api import detect_bp
from web.pages import web_bp
from api.stats_api import stats_bp
from api.robot_api import robot_bp
from api.train_api import train_bp


migrate = Migrate()


def seed_everything(seed=42):
    seed_random_state(seed=seed, np_module=np, torch_module=torch)


def ensure_bootstrap_admin(app):
    ensure_bootstrap_admin_impl(
        app=app,
        db_obj=db,
        user_model=User,
        os_module=os,
        logger=logging.getLogger(__name__),
    )


def ensure_ownership_schema(app):
    ensure_ownership_schema_impl(
        app=app,
        db_obj=db,
        logger=logging.getLogger(__name__),
    )


def _mask_database_uri(database_uri):
    return mask_database_uri(database_uri)


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.update(load_yaml_runtime_overrides(app.config.get('BASE_DIR')))
    if config_overrides:
        app.config.update(config_overrides)

    train_max_content_length = app.config.get('TRAIN_MAX_CONTENT_LENGTH')
    max_content_length = app.config.get('MAX_CONTENT_LENGTH')
    if isinstance(train_max_content_length, int) and train_max_content_length > 0:
        if not isinstance(max_content_length, int) or max_content_length < train_max_content_length:
            app.config['MAX_CONTENT_LENGTH'] = train_max_content_length

    seed_everything(app.config.get('SEED', 42))

    configure_root_logging(app)
    log_detection_dependency_report(logging.getLogger(__name__))

    if app.config.get('SECRET_KEY', '') in ('', 'change-this-to-a-random-secret', 'change-this-in-production', 'dev-key'):
        logging.warning(
            'SECRET_KEY is set to an insecure default value. '
            'Set the SECRET_KEY environment variable before deploying to production.'
        )

    logging.info('Active database URI: %s', _mask_database_uri(app.config.get('SQLALCHEMY_DATABASE_URI')))

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(app.config.get('BASE_DIR', app.root_path), 'migrations'))

    with app.app_context():
        os.makedirs(app.config.get('STATIC_DIR', os.path.join(app.root_path, 'static')), exist_ok=True)
        os.makedirs(app.config.get('UPLOAD_DIR', os.path.join(app.root_path, 'static', 'uploads')), exist_ok=True)
        os.makedirs(app.config.get('RESULT_DIR', os.path.join(app.root_path, 'static', 'results')), exist_ok=True)
        if app.config.get('TESTING'):
            db.create_all()
        else:
            apply_database_migrations_impl(
                db,
                upgrade_func=migrate_upgrade,
                stamp_func=migrate_stamp,
                ensure_legacy_schema=lambda: ensure_ownership_schema(app),
                logger=logging.getLogger(__name__),
            )
        ensure_bootstrap_admin(app)
        recover_interrupted_jobs_impl(db, DetectTask, TrainJob, logger=logging.getLogger(__name__))

    register_blueprints(
        app,
        [
            (detect_bp, '/api'),
            (web_bp, None),
            (stats_bp, '/api/stats'),
            (robot_bp, '/api/robot'),
            (train_bp, '/api/train'),
        ],
    )
    register_error_handler(app)
    register_health_route(app)

    return app


if __name__ == "__main__":
    app = create_app()

    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
