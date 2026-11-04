from datetime import datetime

from flask import jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from database.db import db
from database.models import Robot

HEARTBEAT_TIMEOUT = 15
CONTROL_COMMANDS = {
    'FORWARD', 'BACK', 'LEFT', 'RIGHT', 'STOP',
    'PICK_TRASH', 'RESET', 'PAUSE', 'RESUME',
    'SLOW_FORWARD', 'FAST_FORWARD', 'SPIN_LEFT', 'SPIN_RIGHT',
    'HOLD_POSITION', 'CANCEL_NAVIGATION', 'RETURN_HOME', 'DOCK',
}

COMMAND_ALIASES = {
    'BACKWARD': 'BACK',
    'REVERSE': 'BACK',
    'EMERGENCY_STOP': 'STOP',
    'PICK': 'PICK_TRASH',
    'GRAB': 'PICK_TRASH',
    'SLOW': 'SLOW_FORWARD',
    'FAST': 'FAST_FORWARD',
    'ROTATE_LEFT': 'SPIN_LEFT',
    'ROTATE_RIGHT': 'SPIN_RIGHT',
    'CANCEL_NAV': 'CANCEL_NAVIGATION',
    'GO_HOME': 'RETURN_HOME',
    'CHARGE': 'DOCK',
}


def read_client_ip():
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.headers.get('X-Real-IP') or request.remote_addr


def apply_robot_fields(robot, payload, default_status=None):
    if 'lat' in payload:
        robot.current_lat = payload.get('lat')
    if 'lng' in payload:
        robot.current_lng = payload.get('lng')

    if payload.get('battery') is not None:
        try:
            robot.battery = int(payload.get('battery'))
        except (TypeError, ValueError):
            pass

    if payload.get('status') is not None:
        robot.status = payload.get('status')
    elif default_status:
        robot.status = default_status

    ip = read_client_ip()
    if ip:
        robot.ip_address = ip

    if payload.get('config'):
        try:
            robot.config = payload.get('config')
        except (AttributeError, TypeError, ValueError):
            pass

    robot.last_heartbeat = datetime.now()


def take_next_command(robot):
    command = robot.next_command or 'IDLE'
    robot.next_command = 'IDLE'
    return command


def resolve_robot_status(robot, now=None, timeout=HEARTBEAT_TIMEOUT):
    now = now or datetime.now()
    is_offline = (not robot.last_heartbeat) or ((now - robot.last_heartbeat).total_seconds() > timeout)
    if is_offline:
        return 'OFFLINE', robot.status != 'OFFLINE'
    return robot.status or 'ONLINE', False


def _json_ok(payload=None, status_code=200):
    body = {'ok': True}
    if payload:
        body.update(payload)
    return jsonify(body), status_code


def _json_error(message, status_code=400):
    return jsonify({'ok': False, 'msg': message}), status_code


def _json_from_request():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload, None
    return None, _json_error('请求体必须是 JSON 对象', 400)


def _get_robot_or_none(robot_id):
    if robot_id is None:
        return None
    return db.session.get(Robot, robot_id)


def _get_robot_by_device_id(device_id):
    if not device_id:
        return None
    return Robot.query.filter_by(device_id=device_id).first()


def _commit_or_error(action_text):
    try:
        db.session.commit()
        return None
    except SQLAlchemyError:
        db.session.rollback()
        return _json_error(f'{action_text}失败，请稍后重试', 500)


def _parse_navigation_payload(payload):
    try:
        robot_id = int(payload.get('id'))
        latitude = float(payload.get('lat'))
        longitude = float(payload.get('lng'))
    except (TypeError, ValueError):
        return None, None, None, _json_error('导航参数格式错误', 400)

    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None, None, None, _json_error('导航坐标超出范围', 400)

    return robot_id, latitude, longitude, None


def _normalize_command(command_value):
    if command_value is None:
        return None
    command = str(command_value).strip().upper()
    if not command:
        return None
    return COMMAND_ALIASES.get(command, command)


def _build_robot_item(robot, status):
    return {
        'id': robot.id,
        'device_id': robot.device_id,
        'name': robot.name,
        'owner_user_id': getattr(robot, 'owner_user_id', None),
        'status': status,
        'lat': getattr(robot, 'current_lat', None),
        'lng': getattr(robot, 'current_lng', None),
        'battery': getattr(robot, 'battery', None),
        'ip_address': robot.ip_address,
        'last_heartbeat': robot.last_heartbeat.isoformat() if robot.last_heartbeat else None,
        'next_command': robot.next_command,
        'target': {'lat': robot.target_lat, 'lng': robot.target_lng},
    }


def _find_robot_by_device_or_error(payload):
    device_id = payload.get('device_id')
    robot = _get_robot_by_device_id(device_id)
    if not robot:
        return None, jsonify({'ok': False, 'msg': '设备未注册'}), 403
    return robot, None, None


def _find_robot_by_id_or_error(payload, field_name='id'):
    robot = _get_robot_or_none(payload.get(field_name))
    if not robot:
        return None, None, None
    return robot, None, None
