"""Shared session-auth helpers used by the API and web blueprints."""

from functools import wraps

from flask import jsonify, session

from database.db import db
from database.models import User


def get_session_user():
    """Return the logged-in User for this request, or None."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)


def is_admin_user(user):
    return bool(user and getattr(user, 'role', '') == 'admin')


def login_required(view_func):
    """Reject the request with a JSON 401 unless a user is logged in."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not get_session_user():
            return jsonify({'ok': False, 'message': '请先登录'}), 401
        return view_func(*args, **kwargs)

    return wrapper


def admin_required(view_func):
    """Reject the request with JSON 401/403 unless an admin is logged in."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = get_session_user()
        if not user:
            return jsonify({'ok': False, 'message': '请先登录'}), 401
        if not is_admin_user(user):
            return jsonify({'ok': False, 'message': '需要管理员权限'}), 403
        return view_func(*args, **kwargs)

    return wrapper
