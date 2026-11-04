from datetime import datetime

from sqlalchemy import func

from api.stats_data_helpers import (
    build_line_data,
    build_location_points,
    build_pie_data,
    build_robot_snapshot,
    persist_robot_status_updates,
)
from database.db import db
from database.models import DetectItem, DetectTask
def build_summary_payload(load_task_items_option, current_user, is_admin_checker):
    is_admin = bool(is_admin_checker(current_user))
    current_user_id = getattr(current_user, 'id', None)

    task_query = DetectTask.query
    if load_task_items_option is not None:
        task_query = task_query.options(load_task_items_option)

    if not is_admin:
        task_query = task_query.filter(DetectTask.user_id == current_user_id)

    tasks = task_query.filter(DetectTask.latitude.isnot(None)).all()
    locations = build_location_points(tasks)
    pie_data = build_pie_data(current_user=current_user, is_admin_checker=is_admin_checker)

    trend_rows = db.session.query(
        func.date(DetectTask.created_at).label('date'),
        DetectItem.label.label('label'),
        func.count(DetectItem.id).label('count')
    ).join(
        DetectTask, DetectItem.task_id == DetectTask.id
    ).filter(
        DetectItem.label.isnot(None),
        DetectItem.label != ''
    )

    if not is_admin:
        trend_rows = trend_rows.filter(DetectTask.user_id == current_user_id)

    trend_rows = trend_rows.group_by(
        'date', DetectItem.label
    ).order_by(
        'date', DetectItem.label
    ).all()

    line_data = build_line_data(trend_rows)

    now = datetime.now()
    robot_list, robots_to_update = build_robot_snapshot(
        now,
        current_user=current_user,
        is_admin_checker=is_admin_checker,
    )
    persist_robot_status_updates(robots_to_update)

    return {
        'ok': True,
        'locations': locations,
        'pie_data': pie_data,
        'line_data': line_data,
        'robot_list': robot_list,
    }
