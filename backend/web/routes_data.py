import json

from flask import jsonify, request

from .blueprint import web_bp
from .services_data import (
    build_items_payload,
    build_task_detail_payload,
    build_tasks_payload,
)
from .helpers import (
    _get_current_user,
    _is_admin_user,
    _load_task_with_items,
    _parse_page_number,
    _query_latest_items,
    _query_latest_tasks,
    _serialize_detect_item,
    _serialize_detect_item_row,
    _serialize_robot,
    _serialize_task,
    _delete_task_with_items,
    api_login_required,
)
from database.db import db
from database.models import OpsLog, Robot


_MAX_LOG_ACTION_LEN = 255


def _current_user_can_delete_results():
    return _is_admin_user(_get_current_user())


def _can_access_robot(current_user, robot):
    if _is_admin_user(current_user):
        return True
    return getattr(robot, 'owner_user_id', None) == getattr(current_user, 'id', None)


def _request_page_number():
    return _parse_page_number(request.args.get('page'))


def _read_trimmed_payload_text(payload, key, max_len):
    return str(payload.get(key) or '').strip()[:max_len]


def _build_ops_action(message, category, path, source):
    parts = []
    if category:
        parts.append(f'[{category}]')
    if source:
        parts.append(f'({source})')
    parts.append(str(message or ''))
    if path:
        parts.append(f'@{path}')
    action = ' '.join(part for part in parts if part).strip()
    return action[:_MAX_LOG_ACTION_LEN]


@web_bp.route('/api/web/tasks', methods=['GET'])
@api_login_required
def get_tasks_json():
    current_user = _get_current_user()
    pagination = _query_latest_tasks(_request_page_number(), current_user=current_user)
    payload = build_tasks_payload(
        pagination=pagination,
        can_delete=_current_user_can_delete_results(),
        serialize_task=_serialize_task,
    )
    return jsonify(payload)


@web_bp.route('/api/web/items', methods=['GET'])
@api_login_required
def get_items_json():
    current_user = _get_current_user()
    pagination = _query_latest_items(_request_page_number(), current_user=current_user)
    payload = build_items_payload(
        pagination=pagination,
        can_delete=_current_user_can_delete_results(),
        serialize_item_row=_serialize_detect_item_row,
    )
    return jsonify(payload)


@web_bp.route('/api/web/tasks/<int:task_id>', methods=['GET'])
@api_login_required
def get_task_detail_json(task_id):
    current_user = _get_current_user()
    task = _load_task_with_items(task_id, current_user=current_user)
    payload = build_task_detail_payload(
        task=task,
        can_delete=_current_user_can_delete_results(),
        serialize_task=_serialize_task,
        serialize_item=_serialize_detect_item,
    )
    return jsonify(payload)


@web_bp.route('/api/web/tasks/<int:task_id>/delete', methods=['POST'])
@api_login_required
def delete_result_json(task_id):
    if not _current_user_can_delete_results():
        return jsonify({'ok': False, 'message': '只有管理员可以删除检测结果'}), 403

    _delete_task_with_items(task_id)
    return jsonify({'ok': True, 'message': f'任务 #{task_id} 已删除'})


@web_bp.route('/api/web/robots/<int:robot_id>', methods=['GET'])
@api_login_required
def get_robot_detail_json(robot_id):
    current_user = _get_current_user()
    robot = db.get_or_404(Robot, robot_id)
    if not _can_access_robot(current_user, robot):
        return jsonify({'ok': False, 'message': '无权限访问该机器人'}), 403
    return jsonify({
        'ok': True,
        'robot': _serialize_robot(robot),
    })


@web_bp.route('/api/web/client-log', methods=['POST'])
def write_client_log_json():
    payload = request.get_json(silent=True) or {}

    message = _read_trimmed_payload_text(payload, 'message', 512)
    if not message:
        return jsonify({'ok': False, 'message': '日志内容不能为空'}), 400

    category = _read_trimmed_payload_text(payload, 'category', 24)
    path = _read_trimmed_payload_text(payload, 'path', 120)
    source = _read_trimmed_payload_text(payload, 'source', 40)

    # Preserve optional structured metadata as a JSON suffix when supplied.
    meta = payload.get('meta')
    if meta is not None:
        try:
            meta_text = json.dumps(meta, ensure_ascii=False, separators=(',', ':'))
            message = f'{message} meta={meta_text[:160]}'
        except (TypeError, ValueError):
            pass

    current_user = _get_current_user()
    log_item = OpsLog()
    log_item.user_id = getattr(current_user, 'id', None)
    log_item.action = _build_ops_action(message, category, path, source)
    db.session.add(log_item)
    db.session.commit()

    return jsonify({'ok': True, 'id': log_item.id})
