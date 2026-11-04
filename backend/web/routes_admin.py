from flask import jsonify, request

from database.db import db
from database.models import User
from .blueprint import web_bp
from .helpers import (
    _create_user,
    _find_user_by_username,
    _get_current_user,
    _is_admin_user,
    _normalize_secret,
    _serialize_user,
    api_login_required,
)
from .services_auth import AuthValidationError, ensure_register_input


_ROLE_USER = 'user'
_ROLE_ADMIN = 'admin'


def _normalize_role(raw_role):
    role = _normalize_secret(raw_role).lower()
    if role not in {_ROLE_USER, _ROLE_ADMIN}:
        return None
    return role


def _require_admin_user():
    current_user = _get_current_user()
    if not _is_admin_user(current_user):
        return None, (jsonify({'ok': False, 'message': '只有管理员可以管理用户'}), 403)
    return current_user, None


def _count_admin_users():
    return User.query.filter_by(role=_ROLE_ADMIN).count()


def _serialize_user_admin_row(user, current_user_id):
    payload = _serialize_user(user) or {}
    payload['is_current_user'] = bool(current_user_id and user.id == current_user_id)
    return payload


def _validate_admin_user_profile_input(
    username,
    organization,
    password,
    confirm_password,
    current_user_id=None,
):
    if not username or not organization:
        return '请完整填写用户信息', 400
    if len(username) < 3 or len(username) > 50:
        return '用户名长度需在 3-50 个字符之间', 400
    if len(organization) > 120:
        return '所属单位长度不能超过 120 个字符', 400

    if password or confirm_password:
        if len(password) < 6:
            return '密码至少 6 位', 400
        if password != confirm_password:
            return '两次输入的密码不一致', 400

    existing = _find_user_by_username(username)
    if existing and existing.id != current_user_id:
        return '用户名已存在，请更换', 409

    return None, None


@web_bp.route('/api/web/admin/users', methods=['GET'])
@api_login_required
def list_admin_users_json():
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'ok': False, 'message': '请先登录'}), 401

    current_user_id = getattr(current_user, 'id', None)
    is_admin = _is_admin_user(current_user)

    if not is_admin:
        own_user = db.session.get(User, current_user_id)
        if not own_user:
            return jsonify({'ok': False, 'message': '当前用户不存在'}), 404

        own_payload = _serialize_user_admin_row(own_user, current_user_id)
        own_payload['is_self_scope'] = True
        return jsonify({
            'ok': True,
            'can_manage': False,
            'users': [own_payload],
            'summary': {
                'total': 1,
                'admin_count': 1 if own_user.role == _ROLE_ADMIN else 0,
                'user_count': 1 if own_user.role != _ROLE_ADMIN else 0,
            },
        })

    users = User.query.order_by(User.id.asc()).all()
    admin_count = sum(1 for item in users if item.role == _ROLE_ADMIN)

    return jsonify({
        'ok': True,
        'can_manage': True,
        'users': [_serialize_user_admin_row(item, current_user_id) for item in users],
        'summary': {
            'total': len(users),
            'admin_count': admin_count,
            'user_count': len(users) - admin_count,
        },
    })


@web_bp.route('/api/web/users/me/update', methods=['POST'])
@api_login_required
def update_current_user_profile_json():
    current_user = _get_current_user()
    if not current_user:
        return jsonify({'ok': False, 'message': '请先登录'}), 401

    payload = request.get_json(silent=True) or {}
    username = _normalize_secret(payload.get('username'))
    organization = _normalize_secret(payload.get('organization'))
    password = _normalize_secret(payload.get('password'))
    confirm_password = _normalize_secret(payload.get('confirm_password'))

    error_message, status_code = _validate_admin_user_profile_input(
        username,
        organization,
        password,
        confirm_password,
        current_user_id=current_user.id,
    )
    if error_message:
        return jsonify({'ok': False, 'message': error_message}), status_code

    current_user.username = username
    current_user.organization = organization
    if password:
        current_user.set_password(password)
    db.session.commit()

    return jsonify({
        'ok': True,
        'message': '个人信息更新成功',
        'user': _serialize_user(current_user),
    })


@web_bp.route('/api/web/admin/users', methods=['POST'])
@api_login_required
def create_admin_user_json():
    _, error_response = _require_admin_user()
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    username = _normalize_secret(payload.get('username'))
    password = _normalize_secret(payload.get('password'))
    confirm_password = _normalize_secret(payload.get('confirm_password'))
    security_code = _normalize_secret(payload.get('security_code'))
    organization = _normalize_secret(payload.get('organization'))
    role = _normalize_role(payload.get('role') or _ROLE_USER)

    if role is None:
        return jsonify({'ok': False, 'message': '角色仅支持 user 或 admin'}), 400

    try:
        ensure_register_input(
            username,
            password,
            confirm_password,
            security_code,
            organization,
            _find_user_by_username,
        )
    except AuthValidationError as error:
        return jsonify({'ok': False, 'message': error.message}), error.status_code

    user = _create_user(username, password, security_code, role=role, organization=organization)

    return jsonify({
        'ok': True,
        'message': '用户创建成功',
        'user': _serialize_user(user),
    })


@web_bp.route('/api/web/admin/users/<int:user_id>/role', methods=['POST'])
@api_login_required
def update_admin_user_role_json(user_id):
    current_user, error_response = _require_admin_user()
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    next_role = _normalize_role(payload.get('role'))
    if next_role is None:
        return jsonify({'ok': False, 'message': '角色仅支持 user 或 admin'}), 400

    target_user = db.get_or_404(User, user_id)
    if target_user.role == next_role:
        return jsonify({'ok': True, 'message': '角色未发生变化', 'user': _serialize_user(target_user)})

    if target_user.id == current_user.id and next_role != _ROLE_ADMIN:
        return jsonify({'ok': False, 'message': '不能将当前登录管理员降级'}), 400

    if target_user.role == _ROLE_ADMIN and next_role != _ROLE_ADMIN and _count_admin_users() <= 1:
        return jsonify({'ok': False, 'message': '系统至少需要保留一个管理员账号'}), 400

    target_user.role = next_role
    db.session.commit()

    return jsonify({
        'ok': True,
        'message': '用户角色更新成功',
        'user': _serialize_user(target_user),
    })


@web_bp.route('/api/web/admin/users/<int:user_id>/update', methods=['POST'])
@api_login_required
def update_admin_user_profile_json(user_id):
    current_user, error_response = _require_admin_user()
    if error_response:
        return error_response

    target_user = db.get_or_404(User, user_id)
    if target_user.id == current_user.id:
        return jsonify({'ok': False, 'message': '请在个人中心修改当前登录用户信息'}), 400

    payload = request.get_json(silent=True) or {}
    username = _normalize_secret(payload.get('username'))
    organization = _normalize_secret(payload.get('organization'))
    password = _normalize_secret(payload.get('password'))
    confirm_password = _normalize_secret(payload.get('confirm_password'))

    error_message, status_code = _validate_admin_user_profile_input(
        username,
        organization,
        password,
        confirm_password,
        current_user_id=target_user.id,
    )
    if error_message:
        return jsonify({'ok': False, 'message': error_message}), status_code

    target_user.username = username
    target_user.organization = organization
    if password:
        target_user.set_password(password)
    db.session.commit()

    return jsonify({
        'ok': True,
        'message': '用户信息更新成功',
        'user': _serialize_user(target_user),
    })


@web_bp.route('/api/web/admin/users/<int:user_id>/delete', methods=['POST'])
@api_login_required
def delete_admin_user_json(user_id):
    current_user, error_response = _require_admin_user()
    if error_response:
        return error_response

    target_user = db.get_or_404(User, user_id)

    if target_user.id == current_user.id:
        return jsonify({'ok': False, 'message': '不能删除当前登录用户'}), 400

    if target_user.role == _ROLE_ADMIN and _count_admin_users() <= 1:
        return jsonify({'ok': False, 'message': '系统至少需要保留一个管理员账号'}), 400

    db.session.delete(target_user)
    db.session.commit()

    return jsonify({
        'ok': True,
        'message': '用户删除成功',
    })