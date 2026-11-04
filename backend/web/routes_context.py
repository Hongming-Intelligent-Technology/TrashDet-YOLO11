import os

from flask import current_app, g

from .blueprint import web_bp
from .helpers import _get_current_user


@web_bp.before_app_request
def load_logged_in_user():
    g.auth_user = _get_current_user()


@web_bp.app_context_processor
def inject_auth_user():
    static_version = 'dev'
    try:
        static_root = os.path.join(current_app.static_folder or '', 'spa')
        candidate_files = [
            os.path.join(static_root, 'app.js'),
            os.path.join(static_root, 'app.css'),
        ]
        existing_mtimes = [
            os.path.getmtime(file_path)
            for file_path in candidate_files
            if os.path.isfile(file_path)
        ]
        if existing_mtimes:
            static_version = str(int(max(existing_mtimes)))
    except (OSError, TypeError, ValueError):
        pass

    return {
        'auth_user': getattr(g, 'auth_user', None),
        'static_asset_version': static_version,
    }
