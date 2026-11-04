from functools import wraps
import os
from typing import Any, cast

from flask import (
    current_app,
    get_flashed_messages,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)
from sqlalchemy.orm import selectinload

from api.robot_api import HEARTBEAT_TIMEOUT, resolve_robot_status
from database.db import db
from database.models import DetectItem, DetectTask, User
from .services_captcha import (
    _format_captcha_meta,
    _is_captcha_enforced,
    _issue_captcha_payload,
    _verify_captcha_payload,
)
from .utils import _normalize_secret

APP_TITLE = 'EcoGuard 垃圾拾捡机器人管理系统'
DEFAULT_LOGIN_NEXT = '/'


def _get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)


def _is_admin_user(user):
    return bool(user and getattr(user, 'role', '') == 'admin')


def _find_user_by_username(username):
    return User.query.filter_by(username=username).first()


def _captcha_error_response(message, status_code=400, meta=None):
    body = {
        'ok': False,
        'message': str(message),
    }
    body.update(_format_captcha_meta(meta))
    return jsonify(body), status_code


def _validate_next_path(next_path):
    if not next_path:
        return None
    if next_path.startswith('/') and not next_path.startswith('//'):
        return next_path
    return None


def _parse_page_number(raw_value):
    try:
        page_number = int(raw_value)
    except (TypeError, ValueError):
        return 1
    return page_number if page_number > 0 else 1


def _query_latest_tasks(page_number, page_size=16, current_user=None):
    query = DetectTask.query
    if not _is_admin_user(current_user):
        query = query.filter(DetectTask.user_id == getattr(current_user, 'id', None))

    return query.order_by(DetectTask.id.desc()).paginate(
        page=page_number,
        per_page=page_size,
        error_out=False,
    )


def _query_latest_items(page_number, page_size=16, current_user=None):
    query = DetectItem.query.options(selectinload(cast(Any, DetectItem).task)).join(DetectTask, DetectItem.task_id == DetectTask.id)
    if not _is_admin_user(current_user):
        query = query.filter(DetectTask.user_id == getattr(current_user, 'id', None))

    return query.order_by(DetectItem.id.desc()).paginate(
        page=page_number,
        per_page=page_size,
        error_out=False,
    )


def _load_task_with_items(task_id, current_user=None):
    query = DetectTask.query.options(selectinload(cast(Any, DetectTask).items)).filter_by(id=task_id)
    if not _is_admin_user(current_user):
        query = query.filter(DetectTask.user_id == getattr(current_user, 'id', None))
    return query.first_or_404()


def _delete_task_files(task):
    for relative_path in (task.source_path, task.result_path):
        if not relative_path:
            continue
        normalized_path = os.path.normpath(relative_path)
        if os.path.isabs(normalized_path):
            absolute_path = normalized_path
        else:
            absolute_path = os.path.normpath(os.path.join(current_app.root_path, normalized_path))
        if os.path.isfile(absolute_path):
            try:
                os.remove(absolute_path)
            except OSError:
                pass


def _delete_task_with_items(task_id):
    task = db.get_or_404(DetectTask, task_id)
    DetectItem.query.filter_by(task_id=task.id).delete()
    _delete_task_files(task)
    db.session.delete(task)
    db.session.commit()


def _create_user(username, password, security_code, role='user', organization=''):
    user = User(username=username)
    user.role = role or 'user'
    user.organization = _normalize_secret(organization)
    user.set_password(password)
    user.set_security_code(security_code)
    db.session.add(user)
    db.session.commit()
    return user


def _serialize_user(user):
    if not user:
        return None
    return {
        'id': user.id,
        'username': user.username,
        'organization': user.organization,
        'role': user.role,
    }


def _serialize_flash_messages():
    messages = get_flashed_messages(with_categories=True)
    return [
        {
            'category': category,
            'message': message,
        }
        for category, message in messages
    ]


def _serialize_task(task):
    payload = task.to_dict() if hasattr(task, 'to_dict') else {}
    payload['display_location'] = (
        f"{task.latitude}, {task.longitude}"
        if task.latitude is not None and task.longitude is not None
        else (task.location or '-')
    )
    return payload


def _serialize_detect_item(item):
    return {
        'id': item.id,
        'task_id': item.task_id,
        'label': item.label,
        'confidence': item.confidence,
        'handle_state': item.handle_state,
        'bbox': [item.x1, item.y1, item.x2, item.y2],
        'frame_index': item.frame_index,
        'snapshot_path': item.snapshot_path,
        'captured_at': item.captured_at.isoformat() if item.captured_at else None,
    }


def _serialize_detect_item_row(item):
    task = item.task
    display_location = '-'
    if task:
        display_location = (
            f"{task.latitude}, {task.longitude}"
            if task.latitude is not None and task.longitude is not None
            else (task.location or '-')
        )

    return {
        'id': item.id,
        'task_id': item.task_id,
        'label': item.label,
        'confidence': item.confidence,
        'handle_state': item.handle_state,
        'bbox': [item.x1, item.y1, item.x2, item.y2],
        'frame_index': item.frame_index,
        'snapshot_path': item.snapshot_path,
        'captured_at': item.captured_at.isoformat() if item.captured_at else None,
        'source_type': getattr(task, 'source_type', None),
        'device_id': getattr(task, 'device_id', None),
        'task_status': getattr(task, 'status', None),
        'display_location': display_location,
        'task_created_at': task.created_at.isoformat() if task and task.created_at else None,
    }


def _serialize_robot(robot):
    status, _ = resolve_robot_status(robot, timeout=HEARTBEAT_TIMEOUT)
    return {
        'id': robot.id,
        'device_id': robot.device_id,
        'name': robot.name,
        'status': status,
        'battery': robot.battery,
        'ip_address': robot.ip_address,
        'lat': robot.current_lat,
        'lng': robot.current_lng,
        'target': {
            'lat': robot.target_lat,
            'lng': robot.target_lng,
        },
        'owner_user_id': robot.owner_user_id,
        'last_heartbeat': robot.last_heartbeat.isoformat() if robot.last_heartbeat else None,
    }


def _render_spa(page_title='EcoGuard', next_path=None):
    initial_state = {
        'authUser': _serialize_user(_get_current_user()),
        'flashMessages': _serialize_flash_messages(),
        'nextPath': next_path,
        'requestPath': request.path,
    }
    return render_template('spa.html', page_title=page_title, initial_state=initial_state)


def _render_main_spa(next_path=None):
    return _render_spa(APP_TITLE, next_path=next_path)


def api_login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not _get_current_user():
            return jsonify({'ok': False, 'message': '请先登录'}), 401
        return view_func(*args, **kwargs)

    return wrapper


def _redirect_to_login_for_page(next_path=None):
    normalized_next = _validate_next_path(next_path or request.path)
    if normalized_next:
        return redirect(f'/login?next={normalized_next}')
    return redirect('/login')


def page_login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not _get_current_user():
            return _redirect_to_login_for_page()
        return view_func(*args, **kwargs)

    return wrapper
