from collections import defaultdict
import logging

from sqlalchemy import distinct, func
from sqlalchemy.exc import SQLAlchemyError

from api.robot_api import HEARTBEAT_TIMEOUT, resolve_robot_status
from database.db import db
from database.models import DetectItem, DetectTask, Robot


logger = logging.getLogger(__name__)


def _append_trend_point(day, trash_type, amount, days, seen_days, type_names, seen_types, line_map):
    day_key = str(day)
    if day_key not in seen_days:
        days.append(day_key)
        seen_days.add(day_key)
    if trash_type not in seen_types:
        type_names.append(trash_type)
        seen_types.add(trash_type)
    line_map[trash_type][day_key] = int(amount)


def build_location_points(tasks):
    points = []
    for task in tasks:
        labels = sorted({item.label for item in task.items if item.label})
        points.append({
            'id': task.id,
            'lat': task.latitude,
            'lng': task.longitude,
            'trash_types': ', '.join(labels) if labels else '未知',
        })
    return points


def build_pie_data(current_user=None, is_admin_checker=None):
    is_admin = bool(is_admin_checker and is_admin_checker(current_user))
    current_user_id = getattr(current_user, 'id', None)

    count_rows_query = db.session.query(
        DetectItem.label, func.count(DetectItem.id)
    ).join(
        DetectTask, DetectItem.task_id == DetectTask.id
    ).filter(
        DetectItem.label.isnot(None),
        DetectItem.label != ''
    )

    if not is_admin:
        count_rows_query = count_rows_query.filter(DetectTask.user_id == current_user_id)

    count_rows = count_rows_query.group_by(DetectItem.label).all()
    return [{'name': row[0], 'value': row[1]} for row in count_rows]


def build_line_data(trend_rows):
    days = []
    seen_days = set()
    type_names = []
    seen_types = set()
    line_map = defaultdict(dict)

    for day, trash_type, amount in trend_rows:
        _append_trend_point(
            day=day,
            trash_type=trash_type,
            amount=amount,
            days=days,
            seen_days=seen_days,
            type_names=type_names,
            seen_types=seen_types,
            line_map=line_map,
        )

    series = [
        {
            'name': type_name,
            'values': [line_map[type_name].get(day_key, 0) for day_key in days],
        }
        for type_name in type_names
    ]

    return {
        'labels': days,
        'series': series,
        'values': [sum(item['values'][i] for item in series) for i in range(len(days))] if days else [],
    }


def build_robot_snapshot(now, current_user=None, is_admin_checker=None):
    is_admin = bool(is_admin_checker and is_admin_checker(current_user))
    current_user_id = getattr(current_user, 'id', None)

    if is_admin:
        robots = Robot.query.all()
    else:
        robots = Robot.query.filter_by(owner_user_id=current_user_id).all()

    robot_items = []
    robots_to_update = []
    for robot in robots:
        view_status, should_mark_offline = resolve_robot_status(robot, now=now, timeout=HEARTBEAT_TIMEOUT)
        if should_mark_offline:
            robot.status = 'OFFLINE'
            robots_to_update.append(robot)

        robot_items.append({
            'device_id': robot.device_id,
            'name': robot.name,
            'status': view_status,
            'battery': getattr(robot, 'battery', 75),
            'lat': getattr(robot, 'current_lat', None),
            'lng': getattr(robot, 'current_lng', None),
            'ip_address': robot.ip_address,
            'last_heartbeat': robot.last_heartbeat.isoformat() if robot.last_heartbeat else None,
        })
    return robot_items, robots_to_update


def persist_robot_status_updates(robots_to_update):
    if not robots_to_update:
        return
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        logger.warning('机器人在线状态回写失败: %s', error)
def query_hotspot_source_rows(cutoff_time=None, current_user=None, is_admin_checker=None):
    is_admin = bool(is_admin_checker and is_admin_checker(current_user))
    current_user_id = getattr(current_user, 'id', None)

    filters = [
        DetectTask.latitude.isnot(None),
        DetectTask.longitude.isnot(None),
        DetectItem.label.isnot(None),
        DetectItem.label != '',
    ]
    if not is_admin:
        filters.append(DetectTask.user_id == current_user_id)

    if cutoff_time is not None:
        filters.append(DetectTask.created_at >= cutoff_time)

    return db.session.query(
        DetectTask.created_at.label('created_at'),
        DetectTask.latitude.label('latitude'),
        DetectTask.longitude.label('longitude'),
        DetectItem.label.label('label'),
        func.count(DetectItem.id).label('detection_count'),
        func.count(distinct(DetectTask.id)).label('task_count'),
    ).join(
        DetectItem, DetectItem.task_id == DetectTask.id
    ).filter(
        *filters
    ).group_by(
        DetectTask.id,
        DetectTask.created_at,
        DetectTask.latitude,
        DetectTask.longitude,
        DetectItem.label
    ).all()
