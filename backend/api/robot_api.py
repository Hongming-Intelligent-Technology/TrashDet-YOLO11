import logging
from datetime import datetime
from threading import Lock

from flask import Blueprint, jsonify, request
from api.detect_helpers import lookup_address

from api.robot_helpers import (
    COMMAND_ALIASES,
    CONTROL_COMMANDS,
    HEARTBEAT_TIMEOUT,
    _build_robot_item,
    _commit_or_error,
    _find_robot_by_device_or_error,
    _find_robot_by_id_or_error,
    _get_robot_by_device_id,
    _get_robot_or_none,
    _json_error,
    _json_from_request,
    _json_ok,
    _normalize_command,
    _parse_navigation_payload,
    apply_robot_fields,
    read_client_ip,
    resolve_robot_status,
    take_next_command,
)
from api.robot_route_services import (
    advance_running_patrol,
    apply_navigation_target,
    extract_patrol_waypoints,
    parse_json_text,
    parse_patrol_task_payload,
    parse_patrol_task_update_payload,
    apply_robot_update_payload,
    build_robot_list_snapshot,
    to_json_text,
    validate_register_fields,
)
from database.db import db
from database.models import Robot, RobotPatrolTask
from services.auth import get_session_user as _get_session_user, is_admin_user as _is_admin_user


robot_bp = Blueprint('robot_bp', __name__)
logger = logging.getLogger(__name__)

PATROL_ARRIVAL_THRESHOLD_M = 8.0
_ROBOT_REALTIME_SNAPSHOT = {}
_ROBOT_REALTIME_LOCK = Lock()
_ROBOT_ADDRESS_CACHE = {}
_ROBOT_ADDRESS_CACHE_LOCK = Lock()


def _update_robot_realtime_snapshot(robot):
    if not robot:
        return
    snapshot = {
        'robot_id': robot.id,
        'status': getattr(robot, 'status', None),
        'lat': getattr(robot, 'current_lat', None),
        'lng': getattr(robot, 'current_lng', None),
        'battery': getattr(robot, 'battery', None),
        'ip_address': getattr(robot, 'ip_address', None),
        'last_heartbeat': getattr(robot, 'last_heartbeat', None) or datetime.now(),
        'target_lat': getattr(robot, 'target_lat', None),
        'target_lng': getattr(robot, 'target_lng', None),
    }
    with _ROBOT_REALTIME_LOCK:
        _ROBOT_REALTIME_SNAPSHOT[int(robot.id)] = snapshot


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_robot_address(lat, lng):
    normalized_lat = _to_float_or_none(lat)
    normalized_lng = _to_float_or_none(lng)
    if normalized_lat is None or normalized_lng is None:
        return None
    if not (-90.0 <= normalized_lat <= 90.0 and -180.0 <= normalized_lng <= 180.0):
        return None

    cache_key = (round(normalized_lat, 5), round(normalized_lng, 5))
    with _ROBOT_ADDRESS_CACHE_LOCK:
        cached = _ROBOT_ADDRESS_CACHE.get(cache_key)
    if cached:
        return cached

    resolved = lookup_address(cache_key[0], cache_key[1])
    with _ROBOT_ADDRESS_CACHE_LOCK:
        _ROBOT_ADDRESS_CACHE[cache_key] = resolved
    return resolved


def _build_realtime_payload(robot, payload, default_status=None):
    snapshot = _get_robot_realtime_snapshot(getattr(robot, 'id', None)) or {}
    now = datetime.now()

    payload_lat = _to_float_or_none(payload.get('lat'))
    payload_lng = _to_float_or_none(payload.get('lng'))
    if payload_lat is not None and not (-90.0 <= payload_lat <= 90.0):
        payload_lat = None
    if payload_lng is not None and not (-180.0 <= payload_lng <= 180.0):
        payload_lng = None

    lat = payload_lat if payload_lat is not None else snapshot.get('lat')
    lng = payload_lng if payload_lng is not None else snapshot.get('lng')
    battery = _to_int_or_none(payload.get('battery'))
    if battery is None:
        battery = snapshot.get('battery')
    ip_address = read_client_ip() or snapshot.get('ip_address')

    if payload.get('status') is not None:
        status = payload.get('status')
    elif default_status is not None:
        status = default_status
    else:
        status = snapshot.get('status') or getattr(robot, 'status', None)

    return {
        'status': status,
        'lat': lat,
        'lng': lng,
        'battery': battery,
        'ip_address': ip_address,
        'last_heartbeat': now,
    }


def _persist_last_position_if_needed(robot, realtime_payload, command, running_task, original_lat=None, original_lng=None):
    if command != 'IDLE' or running_task is not None:
        return False

    lat = realtime_payload.get('lat')
    lng = realtime_payload.get('lng')
    if lat is None or lng is None:
        return False

    db_lat = original_lat
    db_lng = original_lng
    if db_lat is not None and db_lng is not None:
        if abs(float(db_lat) - float(lat)) <= 1e-9 and abs(float(db_lng) - float(lng)) <= 1e-9:
            return False

    robot.current_lat = lat
    robot.current_lng = lng
    return True


def _save_realtime_snapshot(robot, realtime_payload):
    snapshot = {
        'robot_id': robot.id,
        'status': realtime_payload.get('status'),
        'lat': realtime_payload.get('lat'),
        'lng': realtime_payload.get('lng'),
        'battery': realtime_payload.get('battery'),
        'ip_address': realtime_payload.get('ip_address'),
        'last_heartbeat': realtime_payload.get('last_heartbeat'),
        'target_lat': getattr(robot, 'target_lat', None),
        'target_lng': getattr(robot, 'target_lng', None),
    }
    with _ROBOT_REALTIME_LOCK:
        _ROBOT_REALTIME_SNAPSHOT[int(robot.id)] = snapshot


def _get_robot_realtime_snapshot(robot_id):
    if robot_id is None:
        return None
    with _ROBOT_REALTIME_LOCK:
        snapshot = _ROBOT_REALTIME_SNAPSHOT.get(int(robot_id))
        if not snapshot:
            return None
        return dict(snapshot)


def _overlay_realtime_snapshot(robot_item, snapshot, timeout_seconds):
    if not snapshot:
        return robot_item

    merged = dict(robot_item)
    merged['lat'] = snapshot.get('lat')
    merged['lng'] = snapshot.get('lng')
    merged['battery'] = snapshot.get('battery')
    merged['ip_address'] = snapshot.get('ip_address')

    last_hb = snapshot.get('last_heartbeat')
    if isinstance(last_hb, datetime):
        merged['last_heartbeat'] = last_hb.isoformat()
        age_seconds = (datetime.now() - last_hb).total_seconds()
        if age_seconds > float(timeout_seconds):
            merged['status'] = 'OFFLINE'
        else:
            merged['status'] = snapshot.get('status') or merged.get('status') or 'ONLINE'
    else:
        merged['status'] = snapshot.get('status') or merged.get('status')

    merged['target'] = {
        'lat': snapshot.get('target_lat'),
        'lng': snapshot.get('target_lng'),
    }
    return merged


def _require_ui_user():
    user = _get_session_user()
    if not user:
        return None, _json_error('请先登录', 401)
    return user, None


def _resolve_robot_from_payload(payload):
    robot_id = payload.get('id')
    if robot_id is not None:
        try:
            return _get_robot_or_none(int(robot_id))
        except (TypeError, ValueError):
            return None

    device_id = str(payload.get('device_id') or '').strip()
    if device_id:
        return _get_robot_by_device_id(device_id)
    return None


def _resolve_robot_and_access(payload):
    robot = _resolve_robot_from_payload(payload)
    if not robot:
        return None, _json_error('机器人不存在', 404)

    current_user = _get_session_user()
    if current_user:
        if not _can_access_robot(current_user, robot):
            return None, _json_error('无权限访问该机器人', 403)
        return robot, None

    # Allow device-side control only when no UI session and device_id matches itself.
    device_id = str(payload.get('device_id') or '').strip()
    if not device_id or device_id != str(getattr(robot, 'device_id', '') or ''):
        return None, _json_error('请先登录', 401)
    return robot, None


def _can_access_robot(user, robot):
    if _is_admin_user(user):
        return True
    return getattr(robot, 'owner_user_id', None) == getattr(user, 'id', None)


def _serialize_patrol_task(task):
    waypoints = extract_patrol_waypoints(task, parse_json_text)
    return {
        'id': task.id,
        'robot_id': task.robot_id,
        'name': task.name,
        'inspection_area': parse_json_text(task.inspection_area, []),
        'planned_path': parse_json_text(task.planned_path, []),
        'status': task.status,
        'current_waypoint_index': int(getattr(task, 'current_waypoint_index', 0) or 0),
        'total_waypoints': len(waypoints),
        'created_by_user_id': task.created_by_user_id,
        'created_at': task.created_at.isoformat() if task.created_at else None,
        'updated_at': task.updated_at.isoformat() if task.updated_at else None,
    }


def _get_patrol_task_or_none(task_id):
    if task_id is None:
        return None
    return db.session.get(RobotPatrolTask, task_id)


def _can_access_patrol_task(user, patrol_task):
    if _is_admin_user(user):
        return True
    robot = db.session.get(Robot, patrol_task.robot_id)
    if robot is None:
        return False
    return _can_access_robot(user, robot)


def _get_running_patrol_task(robot_id):
    return RobotPatrolTask.query.filter_by(robot_id=robot_id, status='RUNNING').order_by(RobotPatrolTask.created_at.asc()).first()


def _build_running_waypoints_payload(task):
    if not task or getattr(task, 'status', None) != 'RUNNING':
        return []

    waypoints = extract_patrol_waypoints(task, parse_json_text)
    if not waypoints:
        return []

    index = int(getattr(task, 'current_waypoint_index', 0) or 0)
    if index < 0:
        index = 0
    if index >= len(waypoints):
        return []

    return waypoints[index:]


def _sync_running_patrol_for_robot(robot):
    running_task = _get_running_patrol_task(robot.id)
    if not running_task:
        return

    before_status = running_task.status
    before_index = int(getattr(running_task, 'current_waypoint_index', 0) or 0)
    before_target = (getattr(robot, 'target_lat', None), getattr(robot, 'target_lng', None))
    before_next_command = getattr(robot, 'next_command', None)

    advance_running_patrol(
        robot=robot,
        task=running_task,
        parse_json_text_func=parse_json_text,
        apply_navigation_target_func=apply_navigation_target,
        arrival_threshold_m=PATROL_ARRIVAL_THRESHOLD_M,
    )

    after_status = running_task.status
    after_index = int(getattr(running_task, 'current_waypoint_index', 0) or 0)
    after_target = (getattr(robot, 'target_lat', None), getattr(robot, 'target_lng', None))
    after_next_command = getattr(robot, 'next_command', None)

    if (
        before_status != after_status
        or before_index != after_index
        or before_target != after_target
        or before_next_command != after_next_command
    ):
        logger.info(
            'Patrol progress robot=%s task=%s status=%s->%s index=%s->%s target=%s->%s next_command=%s->%s',
            robot.id,
            running_task.id,
            before_status,
            after_status,
            before_index,
            after_index,
            before_target,
            after_target,
            before_next_command,
            after_next_command,
        )


@robot_bp.route('/heartbeat', methods=['POST'])
def sync_heartbeat():
    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    robot, error_body, error_code = _find_robot_by_device_or_error(payload)
    if not robot:
        if error_body is not None and error_code is not None:
            return error_body, error_code
        return _json_error('设备未注册', 403)

    apply_robot_fields(robot, payload, default_status='ONLINE')

    _sync_running_patrol_for_robot(robot)
    command = take_next_command(robot)
    running_task = _get_running_patrol_task(robot.id)
    if (
        command == 'IDLE'
        and running_task is not None
        and getattr(robot, 'target_lat', None) is not None
        and getattr(robot, 'target_lng', None) is not None
    ):
        command = 'NAVIGATE'
    if command and command != 'IDLE':
        logger.info(
            'Dispatch heartbeat command robot=%s command=%s target=(%s,%s)',
            robot.id,
            command,
            getattr(robot, 'target_lat', None),
            getattr(robot, 'target_lng', None),
        )

    _update_robot_realtime_snapshot(robot)
    commit_error = _commit_or_error('同步心跳')
    if commit_error:
        return commit_error

    remaining_waypoints = _build_running_waypoints_payload(running_task)

    return _json_ok({
        'robot_id': robot.id,
        'command': command,
        'target': {
            'lat': robot.target_lat,
            'lng': robot.target_lng,
        },
        'waypoints': remaining_waypoints,
    })


@robot_bp.route('/status_update', methods=['POST'])
def sync_status():
    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    robot, error_body, error_code = _find_robot_by_device_or_error(payload)
    if not robot:
        if error_body is not None and error_code is not None:
            return error_body, error_code
        return _json_error('设备未注册', 403)

    apply_robot_fields(robot, payload)

    _sync_running_patrol_for_robot(robot)
    command = take_next_command(robot)
    running_task = _get_running_patrol_task(robot.id)
    if (
        command == 'IDLE'
        and running_task is not None
        and getattr(robot, 'target_lat', None) is not None
        and getattr(robot, 'target_lng', None) is not None
    ):
        command = 'NAVIGATE'
    if command and command != 'IDLE':
        logger.info(
            'Dispatch status command robot=%s command=%s target=(%s,%s)',
            robot.id,
            command,
            getattr(robot, 'target_lat', None),
            getattr(robot, 'target_lng', None),
        )

    _update_robot_realtime_snapshot(robot)
    commit_error = _commit_or_error('同步状态')
    if commit_error:
        return commit_error

    remaining_waypoints = _build_running_waypoints_payload(running_task)

    return _json_ok({
        'robot_id': robot.id,
        'command': command,
        'target': {'lat': robot.target_lat, 'lng': robot.target_lng},
        'waypoints': remaining_waypoints,
    })


@robot_bp.route('/register', methods=['POST'])
def create_robot():
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error
    assert current_user is not None

    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    try:
        device_id, name = validate_register_fields(payload)
    except ValueError as error:
        return _json_error(str(error), 400)

    if _get_robot_by_device_id(device_id):
        return jsonify({'ok': False, 'msg': '该设备 ID 已存在'}), 409

    robot = Robot(device_id=device_id, name=name, status='OFFLINE', owner_user_id=current_user.id)
    db.session.add(robot)
    commit_error = _commit_or_error('创建设备')
    if commit_error:
        return commit_error
    return jsonify({'ok': True})


@robot_bp.route('/register_device', methods=['POST'])
def create_robot_device_side():
    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    try:
        device_id, name = validate_register_fields(payload)
    except ValueError as error:
        return _json_error(str(error), 400)

    existing_robot = _get_robot_by_device_id(device_id)
    if existing_robot:
        return _json_ok({'robot_id': existing_robot.id, 'msg': '设备已存在'})

    robot = Robot(device_id=device_id, name=name, status='OFFLINE', owner_user_id=None)
    db.session.add(robot)
    commit_error = _commit_or_error('设备注册')
    if commit_error:
        return commit_error
    return _json_ok({'robot_id': robot.id})


@robot_bp.route('/delete/<int:robot_id>', methods=['POST'])
def remove_robot(robot_id):
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error

    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error('未找到设备', 404)
    if not _can_access_robot(current_user, robot):
        return _json_error('无权限访问该机器人', 403)

    db.session.delete(robot)
    commit_error = _commit_or_error('删除设备')
    if commit_error:
        return commit_error
    return _json_ok()


@robot_bp.route('/address', methods=['GET'])
def get_robot_address():
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error
    assert current_user is not None

    lat = _to_float_or_none(request.args.get('lat'))
    lng = _to_float_or_none(request.args.get('lng'))
    if lat is None or lng is None:
        return _json_error('请提供有效的经纬度参数', 400)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return _json_error('坐标超出有效范围', 400)

    address = _resolve_robot_address(lat, lng)
    if not address:
        return _json_error('地址解析失败', 500)

    return _json_ok({
        'address': address,
        'lat': lat,
        'lng': lng,
    })


@robot_bp.route('/navigate', methods=['POST'])
def send_navigation():
    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    robot, access_error = _resolve_robot_and_access(payload)
    if access_error:
        return access_error
    assert robot is not None

    try:
        latitude = float(payload.get('lat'))
        longitude = float(payload.get('lng'))
    except (TypeError, ValueError):
        return _json_error('导航参数格式错误', 400)
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return _json_error('导航坐标超出范围', 400)

    apply_navigation_target(robot, latitude, longitude)
    commit_error = _commit_or_error('下发导航')
    if commit_error:
        return commit_error
    return _json_ok({'msg': '目标已锁定'})


@robot_bp.route('/commands', methods=['GET'])
def list_control_commands():
    commands = sorted(CONTROL_COMMANDS)
    return _json_ok({'commands': commands})


@robot_bp.route('/control', methods=['POST'])
def send_control():
    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    robot, access_error = _resolve_robot_and_access(payload)
    if access_error:
        return access_error
    assert robot is not None

    command = _normalize_command(payload.get('command'))
    if not command:
        return _json_error('控制指令不能为空', 400)
    if command not in CONTROL_COMMANDS:
        return _json_error('不支持的控制指令', 400)

    robot.next_command = command
    commit_error = _commit_or_error('下发控制')
    if commit_error:
        return commit_error
    return _json_ok({'command': command})


@robot_bp.route('/list', methods=['GET'])
def fetch_robots():
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error
    assert current_user is not None

    if _is_admin_user(current_user):
        robots = Robot.query.all()
    else:
        robots = Robot.query.filter_by(owner_user_id=current_user.id).all()

    robot_items, pending_updates = build_robot_list_snapshot(
        robots=robots,
        resolve_status=resolve_robot_status,
        timeout=HEARTBEAT_TIMEOUT,
        build_item=_build_robot_item,
    )

    if pending_updates:
        commit_error = _commit_or_error('更新离线状态')
        if commit_error:
            return commit_error

    return jsonify({'ok': True, 'robots': robot_items})


@robot_bp.route('/live/list', methods=['GET'])
def fetch_live_robots():
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error
    assert current_user is not None

    if _is_admin_user(current_user):
        robots = Robot.query.all()
    else:
        robots = Robot.query.filter_by(owner_user_id=current_user.id).all()

    robot_items = []
    for robot in robots:
        status, _ = resolve_robot_status(robot, timeout=HEARTBEAT_TIMEOUT)
        base_item = _build_robot_item(robot, status)
        snapshot = _get_robot_realtime_snapshot(robot.id)
        merged_item = _overlay_realtime_snapshot(
            robot_item=base_item,
            snapshot=snapshot,
            timeout_seconds=HEARTBEAT_TIMEOUT,
        )
        robot_items.append(merged_item)

    return jsonify({'ok': True, 'robots': robot_items})


@robot_bp.route('/update', methods=['POST'])
def save_robot_changes():
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error

    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    robot_id = payload.get('id')
    robot = _get_robot_or_none(robot_id)
    if not robot:
        return jsonify({'ok': False, 'msg': '机器人不存在'}), 404
    if not _can_access_robot(current_user, robot):
        return _json_error('无权限访问该机器人', 403)

    try:
        apply_robot_update_payload(
            robot=robot,
            payload=payload,
            normalize_command=_normalize_command,
            control_commands=CONTROL_COMMANDS,
        )
    except ValueError as error:
        return _json_error(str(error), 400)

    commit_error = _commit_or_error('更新设备')
    if commit_error:
        return commit_error
    return jsonify({'ok': True})


@robot_bp.route('/task/create', methods=['POST'])
def create_patrol_task():
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error

    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    try:
        robot_id = int(payload.get('robot_id'))
    except (TypeError, ValueError):
        return _json_error('robot_id 参数错误', 400)

    robot = _get_robot_or_none(robot_id)
    if not robot:
        return _json_error('机器人不存在', 404)
    if not _can_access_robot(current_user, robot):
        return _json_error('无权限访问该机器人', 403)

    try:
        parsed_payload = parse_patrol_task_payload(payload)
    except ValueError as error:
        return _json_error(str(error), 400)

    task = RobotPatrolTask(
        robot_id=robot.id,
        name=parsed_payload['name'],
        inspection_area=to_json_text(parsed_payload['inspection_area']),
        planned_path=to_json_text(parsed_payload['planned_path']),
        status=parsed_payload['status'],
        current_waypoint_index=0,
        created_by_user_id=getattr(current_user, 'id', None),
    )

    if task.status == 'RUNNING':
        running_tasks = RobotPatrolTask.query.filter(
            RobotPatrolTask.robot_id == robot.id,
            RobotPatrolTask.status == 'RUNNING',
        ).all()
        for other_task in running_tasks:
            other_task.status = 'PAUSED'

    db.session.add(task)

    if task.status == 'RUNNING':
        _sync_running_patrol_for_robot(robot)

    commit_error = _commit_or_error('创建巡检任务')
    if commit_error:
        return commit_error

    return _json_ok({'task': _serialize_patrol_task(task)})


@robot_bp.route('/task/list', methods=['GET'])
def list_patrol_tasks():
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error

    request_robot_id = None
    robot_id_arg = request.args.get('robot_id')

    if robot_id_arg is not None:
        try:
            request_robot_id = int(robot_id_arg)
        except (TypeError, ValueError):
            return _json_error('robot_id 参数错误', 400)

    query = RobotPatrolTask.query
    if request_robot_id is not None:
        robot = _get_robot_or_none(request_robot_id)
        if not robot:
            return _json_error('机器人不存在', 404)
        if not _can_access_robot(current_user, robot):
            return _json_error('无权限访问该机器人', 403)
        query = query.filter_by(robot_id=request_robot_id)
    elif not _is_admin_user(current_user):
        owner_robot_ids = [item.id for item in Robot.query.filter_by(owner_user_id=current_user.id).all()]
        if not owner_robot_ids:
            return _json_ok({'tasks': []})
        query = query.filter(RobotPatrolTask.robot_id.in_(owner_robot_ids))

    tasks = query.order_by(RobotPatrolTask.created_at.desc()).all()
    return _json_ok({'tasks': [_serialize_patrol_task(task) for task in tasks]})


@robot_bp.route('/task/<int:task_id>', methods=['GET'])
def get_patrol_task(task_id):
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error

    task = _get_patrol_task_or_none(task_id)
    if not task:
        return _json_error('巡检任务不存在', 404)
    if not _can_access_patrol_task(current_user, task):
        return _json_error('无权限访问该任务', 403)

    return _json_ok({'task': _serialize_patrol_task(task)})


@robot_bp.route('/task/update/<int:task_id>', methods=['POST'])
def update_patrol_task(task_id):
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error

    task = _get_patrol_task_or_none(task_id)
    if not task:
        return _json_error('巡检任务不存在', 404)
    if not _can_access_patrol_task(current_user, task):
        return _json_error('无权限访问该任务', 403)

    payload, payload_error = _json_from_request()
    if payload_error is not None:
        return payload_error
    assert payload is not None

    try:
        updates = parse_patrol_task_update_payload(payload)
    except ValueError as error:
        return _json_error(str(error), 400)

    if 'name' in updates:
        task.name = updates['name']
    if 'inspection_area' in updates:
        task.inspection_area = to_json_text(updates['inspection_area'])
        if task.status in {'PLANNED', 'RUNNING', 'PAUSED'}:
            task.current_waypoint_index = 0
    if 'planned_path' in updates:
        task.planned_path = to_json_text(updates['planned_path'])
        if task.status in {'PLANNED', 'RUNNING', 'PAUSED'}:
            task.current_waypoint_index = 0
    if 'status' in updates:
        old_status = task.status
        task.status = updates['status']
        if task.status == 'PLANNED':
            task.current_waypoint_index = 0
        elif task.status == 'RUNNING':
            if old_status in {'PLANNED', 'DONE', 'CANCELLED'}:
                task.current_waypoint_index = 0

            running_tasks = RobotPatrolTask.query.filter(
                RobotPatrolTask.robot_id == task.robot_id,
                RobotPatrolTask.status == 'RUNNING',
                RobotPatrolTask.id != task.id,
            ).all()
            for other_task in running_tasks:
                other_task.status = 'PAUSED'

            robot = db.session.get(Robot, task.robot_id)
            if robot is not None:
                _sync_running_patrol_for_robot(robot)

    commit_error = _commit_or_error('更新巡检任务')
    if commit_error:
        return commit_error

    return _json_ok({'task': _serialize_patrol_task(task)})


@robot_bp.route('/task/delete/<int:task_id>', methods=['POST'])
def delete_patrol_task(task_id):
    current_user, auth_error = _require_ui_user()
    if auth_error:
        return auth_error

    task = _get_patrol_task_or_none(task_id)
    if not task:
        return _json_error('巡检任务不存在', 404)
    if not _can_access_patrol_task(current_user, task):
        return _json_error('无权限访问该任务', 403)

    db.session.delete(task)
    commit_error = _commit_or_error('删除巡检任务')
    if commit_error:
        return commit_error

    return _json_ok()
