from datetime import datetime
import json
import math


def validate_register_fields(payload):
    device_id = (payload.get('device_id') or '').strip()
    name = (payload.get('name') or '').strip()

    if not device_id or not name:
        raise ValueError('信息不完整')

    if len(device_id) > 50 or len(name) > 100:
        raise ValueError('设备 ID 或名称过长')

    return device_id, name


def apply_navigation_target(robot, latitude, longitude):
    robot.target_lat = latitude
    robot.target_lng = longitude
    robot.next_command = 'NAVIGATE'


def build_robot_list_snapshot(robots, resolve_status, timeout, build_item):
    robot_items = []
    pending_updates = []
    now = datetime.now()

    for robot in robots:
        status, needs_update = resolve_status(robot, now=now, timeout=timeout)
        if needs_update:
            robot.status = 'OFFLINE'
            pending_updates.append(robot)
        robot_items.append(build_item(robot, status))

    return robot_items, pending_updates


def apply_robot_update_payload(robot, payload, normalize_command, control_commands):
    if 'name' in payload:
        new_name = (payload.get('name') or '').strip()
        if len(new_name) > 100:
            raise ValueError('名称过长')
        robot.name = new_name

    if 'status' in payload:
        robot.status = payload.get('status')

    if 'target_lat' in payload and 'target_lng' in payload:
        robot.target_lat = payload.get('target_lat')
        robot.target_lng = payload.get('target_lng')

    if 'next_command' in payload:
        cmd = normalize_command(payload.get('next_command'))
        if cmd and cmd not in control_commands:
            raise ValueError('不支持的控制指令')
        robot.next_command = cmd

    if 'config' in payload:
        robot.config = payload.get('config')


def _parse_geo_point(raw_point, field_name):
    if not isinstance(raw_point, dict):
        raise ValueError(f'{field_name} point must be an object')

    try:
        lat = float(raw_point.get('lat'))
        lng = float(raw_point.get('lng'))
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} contains invalid coordinates')

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        raise ValueError(f'{field_name} contains out-of-range coordinates')

    return {'lat': lat, 'lng': lng}


def parse_patrol_area(raw_area):
    if not isinstance(raw_area, list):
        raise ValueError('inspection_area must be a coordinate list')
    if len(raw_area) < 3:
        raise ValueError('inspection_area requires at least 3 points')

    return [_parse_geo_point(point, 'inspection_area') for point in raw_area]


def parse_planned_path(raw_path):
    if raw_path is None:
        return []
    if not isinstance(raw_path, list):
        raise ValueError('planned_path must be a coordinate list')
    if raw_path and len(raw_path) < 2:
        raise ValueError('planned_path requires at least 2 points')

    return [_parse_geo_point(point, 'planned_path') for point in raw_path]


def parse_patrol_task_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('request body must be a JSON object')

    name = str(payload.get('name') or '').strip()
    if not name:
        raise ValueError('task name is required')
    if len(name) > 120:
        raise ValueError('task name is too long')

    inspection_area = parse_patrol_area(payload.get('inspection_area'))
    planned_path = parse_planned_path(payload.get('planned_path'))

    status = str(payload.get('status') or 'PAUSED').strip().upper()
    if status not in {'PLANNED', 'RUNNING', 'PAUSED', 'DONE', 'CANCELLED'}:
        raise ValueError('invalid task status')

    return {
        'name': name,
        'inspection_area': inspection_area,
        'planned_path': planned_path,
        'status': status,
    }


def parse_patrol_task_update_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('request body must be a JSON object')

    updates = {}

    if 'name' in payload:
        name = str(payload.get('name') or '').strip()
        if not name:
            raise ValueError('task name is required')
        if len(name) > 120:
            raise ValueError('task name is too long')
        updates['name'] = name

    if 'inspection_area' in payload:
        updates['inspection_area'] = parse_patrol_area(payload.get('inspection_area'))

    if 'planned_path' in payload:
        updates['planned_path'] = parse_planned_path(payload.get('planned_path'))

    if 'status' in payload:
        status = str(payload.get('status') or '').strip().upper()
        if status not in {'PLANNED', 'RUNNING', 'PAUSED', 'DONE', 'CANCELLED'}:
            raise ValueError('invalid task status')
        updates['status'] = status

    return updates


def to_json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def parse_json_text(raw_text, default_value):
    if not raw_text:
        return default_value
    try:
        return json.loads(raw_text)
    except (TypeError, ValueError):
        return default_value


def _distance_meters(lat1, lng1, lat2, lng2):
    # Haversine distance in meters to decide whether robot reached a waypoint.
    earth_radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return earth_radius * c


def extract_patrol_waypoints(task, parse_json_text_func):
    planned_path = parse_json_text_func(getattr(task, 'planned_path', None), [])
    inspection_area = parse_json_text_func(getattr(task, 'inspection_area', None), [])
    candidates = planned_path if isinstance(planned_path, list) and planned_path else inspection_area

    base_waypoints = []
    for point in candidates:
        if not isinstance(point, dict):
            continue
        try:
            lat = float(point.get('lat'))
            lng = float(point.get('lng'))
        except (TypeError, ValueError):
            continue
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            base_waypoints.append({'lat': lat, 'lng': lng})

    return base_waypoints


def advance_running_patrol(robot, task, parse_json_text_func, apply_navigation_target_func, arrival_threshold_m=8.0):
    if not task or getattr(task, 'status', None) != 'RUNNING':
        return

    waypoints = extract_patrol_waypoints(task, parse_json_text_func)
    if not waypoints:
        task.status = 'CANCELLED'
        task.current_waypoint_index = 0
        return

    index = int(getattr(task, 'current_waypoint_index', 0) or 0)
    if index < 0:
        index = 0

    if index >= len(waypoints):
        task.status = 'DONE'
        task.current_waypoint_index = len(waypoints)
        return

    waypoint = waypoints[index]
    robot_lat = getattr(robot, 'current_lat', None)
    robot_lng = getattr(robot, 'current_lng', None)
    if robot_lat is not None and robot_lng is not None:
        arrived = _distance_meters(float(robot_lat), float(robot_lng), waypoint['lat'], waypoint['lng']) <= float(arrival_threshold_m)
        if arrived:
            index += 1
            task.current_waypoint_index = index
            if index >= len(waypoints):
                task.status = 'DONE'
                return
            waypoint = waypoints[index]
        # 每次到达都强制下发新目标
        apply_navigation_target_func(robot, waypoint['lat'], waypoint['lng'])
        robot.next_command = 'NAVIGATE'
        return

    # 未到达时也强制下发目标，确保同步
    apply_navigation_target_func(robot, waypoint['lat'], waypoint['lng'])
    robot.next_command = 'NAVIGATE'
