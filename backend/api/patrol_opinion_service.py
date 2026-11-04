from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math

from api.stats_data_helpers import query_hotspot_source_rows


DEFAULT_GRID_SIZE = 0.01


def _query_rows_with_fallback(lookback_days, now, current_user, is_admin_checker, logger=None):
    cutoff_time = now - timedelta(days=lookback_days)
    hotspot_rows = query_hotspot_source_rows(
        cutoff_time,
        current_user=current_user,
        is_admin_checker=is_admin_checker,
    )

    actual_lookback = lookback_days
    if hotspot_rows:
        return hotspot_rows, actual_lookback

    if logger is not None:
        logger.info('巡检意见：%d 天窗口内无数据，降级使用全量历史数据', lookback_days)

    hotspot_rows = query_hotspot_source_rows(
        cutoff_time=None,
        current_user=current_user,
        is_admin_checker=is_admin_checker,
    )
    if not hotspot_rows:
        return hotspot_rows, actual_lookback

    earliest = min(row.created_at for row in hotspot_rows)
    actual_lookback = max(lookback_days, (now - earliest).days + 1)
    return hotspot_rows, actual_lookback


def _record_value(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _grid_floor(value, grid_size):
    return math.floor(float(value) / float(grid_size)) * float(grid_size)


def _average(values):
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _weekday_average(daily_counts, as_of_day):
    values = [count for day, count in daily_counts.items() if day.weekday() == as_of_day.weekday()]
    return _average(values)


def _build_history(daily_counts, as_of_day, days=7):
    labels = []
    values = []
    for offset in range(days - 1, -1, -1):
        day = as_of_day - timedelta(days=offset)
        labels.append(day.strftime('%m-%d'))
        values.append(int(daily_counts.get(day, 0)))
    return {'labels': labels, 'values': values}


def _build_reason(item):
    labels = '、'.join(item['dominant_labels']) if item['dominant_labels'] else '混合垃圾'
    if item['today_count'] > 0:
        return f"近 24 小时仍有 {item['today_count']} 个垃圾目标，{labels}出现更集中。"
    if item['recent_7_avg'] >= item['overall_avg']:
        return f"近 7 天活跃度高于长期均值，{labels}在该区域复现概率较高。"
    return f"该网格在历史数据库中持续有检测记录，建议优先巡检 {labels}。"


def _build_recommendations(hotspots):
    if not hotspots:
        return ['当前还没有足够的历史数据来生成巡检意见。']

    recommendations = []
    top_hotspot = hotspots[0]
    labels = '、'.join(top_hotspot['dominant_labels']) if top_hotspot['dominant_labels'] else '混合垃圾'
    recommendations.append(
        f"优先巡检热点 1，风险分 {top_hotspot['risk_score']}，数据库中近 24 小时约有 {top_hotspot['predicted_count']} 个目标。"
    )
    recommendations.append(
        f"热点 1 的主导垃圾类型为 {labels}，建议按对应清运与分类策略准备巡检。"
    )
    if len(hotspots) > 1:
        total_predicted = round(sum(item['predicted_count'] for item in hotspots[:3]), 2)
        recommendations.append(
            f"前 3 个热点区域合计目标数约为 {total_predicted}，可作为机器人优先巡检路线。"
        )
    return recommendations


def _normalize_risk_score(raw_score, max_raw_score):
    if raw_score <= 0 or max_raw_score <= 0:
        return 0
    return min(100, max(30, int(round((raw_score / max_raw_score) * 100))))


def _aggregate_grid_cells(records, lookback_days, grid_size, as_of_day):
    cutoff_day = as_of_day - timedelta(days=lookback_days - 1)
    cells = {}

    for record in records:
        latitude = _safe_float(_record_value(record, 'latitude'))
        longitude = _safe_float(_record_value(record, 'longitude'))
        created_at = _record_value(record, 'created_at')
        if latitude is None or longitude is None or created_at is None:
            continue

        event_day = created_at.date() if isinstance(created_at, datetime) else None
        if event_day is None or event_day < cutoff_day:
            continue

        label = str(_record_value(record, 'label') or '').strip()
        detection_count = max(_safe_int(_record_value(record, 'detection_count'), 0), 0)
        task_count = max(_safe_int(_record_value(record, 'task_count'), 1), 0)
        if detection_count <= 0:
            continue

        labels = [label] * detection_count if label else []
        grid_lat = _grid_floor(latitude, grid_size)
        grid_lng = _grid_floor(longitude, grid_size)
        grid_id = f'{grid_lat:.4f},{grid_lng:.4f}'
        center_lat = round(grid_lat + (grid_size / 2.0), 6)
        center_lng = round(grid_lng + (grid_size / 2.0), 6)

        cell = cells.setdefault(
            grid_id,
            {
                'grid_id': grid_id,
                'center_lat': center_lat,
                'center_lng': center_lng,
                'daily_counts': defaultdict(int),
                'label_counter': Counter(),
                'task_count': 0,
                'total_detections': 0,
                'last_seen_at': None,
            },
        )
        cell['daily_counts'][event_day] += detection_count
        cell['label_counter'].update(labels)
        cell['task_count'] += max(task_count, 0)
        cell['total_detections'] += detection_count
        if cell['last_seen_at'] is None or created_at > cell['last_seen_at']:
            cell['last_seen_at'] = created_at

    return cells


def _score_grid_cell(cell, as_of_day, lookback_days, forecast_days):
    window_days = [as_of_day - timedelta(days=offset) for offset in range(lookback_days - 1, -1, -1)]
    counts = [int(cell['daily_counts'].get(day, 0)) for day in window_days]
    recent_3_avg = _average(counts[-3:])
    recent_7_avg = _average(counts[-7:])
    overall_avg = _average(counts)
    today_count = counts[-1] if counts else 0
    previous_3_avg = _average(counts[-6:-3]) if len(counts) >= 6 else 0.0
    weekday_baseline = _weekday_average(cell['daily_counts'], as_of_day)
    active_days = sum(1 for value in counts if value > 0)
    recency_days = (as_of_day - cell['last_seen_at'].date()).days if cell['last_seen_at'] else lookback_days
    recency_factor = 1.0 / (1.0 + max(recency_days, 0))
    momentum = recent_3_avg - previous_3_avg

    predicted_count = max(
        0.0,
        (
            recent_3_avg * 0.38
            + recent_7_avg * 0.28
            + overall_avg * 0.18
            + weekday_baseline * 0.16
            + max(momentum, -recent_3_avg) * 0.25
            + today_count * 0.12 * recency_factor
        ) * math.sqrt(max(forecast_days, 1))
    )
    raw_score = predicted_count + (today_count * 0.35) + (recent_7_avg * 0.25) + (active_days / max(lookback_days, 1)) + recency_factor

    return {
        'grid_id': cell['grid_id'],
        'center_lat': cell['center_lat'],
        'center_lng': cell['center_lng'],
        'predicted_count': predicted_count,
        'raw_score': raw_score,
        'today_count': today_count,
        'recent_7_avg': recent_7_avg,
        'overall_avg': overall_avg,
        'active_days': active_days,
        'task_count': cell['task_count'],
        'total_detections': cell['total_detections'],
        'dominant_labels': [label for label, _ in cell['label_counter'].most_common(3)],
        'last_seen_at': cell['last_seen_at'],
        'history': _build_history(cell['daily_counts'], as_of_day),
    }


def build_patrol_opinion_payload(lookback_days, top_k, current_user, is_admin_checker, logger=None):
    now = datetime.now()
    hotspot_rows, actual_lookback = _query_rows_with_fallback(
        lookback_days=lookback_days,
        now=now,
        current_user=current_user,
        is_admin_checker=is_admin_checker,
        logger=logger,
    )

    if not hotspot_rows:
        return {
            'generated_at': now.isoformat(),
            'grid_size': DEFAULT_GRID_SIZE,
            'lookback_days': lookback_days,
            'forecast_days': 1,
            'summary': {'cells_analyzed': 0, 'tasks_used': 0, 'detections_used': 0},
            'chart_data': {'labels': [], 'values': []},
            'hotspots': [],
            'recommendations': ['当前还没有足够的历史数据来生成巡检意见。'],
            'opinion': {'source': 'database_opinion', 'mode': 'database', 'message': '暂无足够数据'},
        }

    as_of_day = now.date()
    cells = _aggregate_grid_cells(hotspot_rows, actual_lookback, DEFAULT_GRID_SIZE, as_of_day)
    if not cells:
        return {
            'generated_at': now.isoformat(),
            'grid_size': DEFAULT_GRID_SIZE,
            'lookback_days': actual_lookback,
            'forecast_days': 1,
            'summary': {'cells_analyzed': 0, 'tasks_used': 0, 'detections_used': 0},
            'chart_data': {'labels': [], 'values': []},
            'hotspots': [],
            'recommendations': ['当前还没有足够的历史数据来生成巡检意见。'],
            'opinion': {'source': 'database_opinion', 'mode': 'database', 'message': '暂无足够数据'},
        }

    scored_cells = [
        _score_grid_cell(cell=cell, as_of_day=as_of_day, lookback_days=actual_lookback, forecast_days=1)
        for cell in cells.values()
    ]
    scored_cells.sort(key=lambda item: (item['predicted_count'], item['recent_7_avg'], item['total_detections']), reverse=True)

    top_cells = scored_cells[:top_k]
    max_raw_score = max((item['raw_score'] for item in top_cells), default=0.0)
    hotspots = []
    for index, item in enumerate(top_cells, start=1):
        risk_score = _normalize_risk_score(item['raw_score'], max_raw_score)
        hotspots.append({
            'rank': index,
            'grid_id': item['grid_id'],
            'center_lat': item['center_lat'],
            'center_lng': item['center_lng'],
            'predicted_count': round(item['predicted_count'], 2),
            'risk_score': risk_score,
            'recent_count': item['today_count'],
            'active_days': item['active_days'],
            'task_count': item['task_count'],
            'dominant_labels': item['dominant_labels'],
            'last_seen_at': item['last_seen_at'].isoformat() if item['last_seen_at'] else None,
            'history': item['history'],
            'reason': _build_reason(item),
        })

    return {
        'generated_at': now.isoformat(),
        'grid_size': DEFAULT_GRID_SIZE,
        'lookback_days': actual_lookback,
        'forecast_days': 1,
        'summary': {
            'cells_analyzed': len(cells),
            'tasks_used': sum(cell['task_count'] for cell in cells.values()),
            'detections_used': sum(cell['total_detections'] for cell in cells.values()),
        },
        'chart_data': {
            'labels': [f'热点 {item["rank"]}' for item in hotspots],
            'values': [item['predicted_count'] for item in hotspots],
        },
        'hotspots': hotspots,
        'recommendations': _build_recommendations(hotspots),
        'opinion': {
            'source': 'database_opinion',
            'mode': 'database',
            'message': hotspots[0]['reason'] if hotspots else '暂无足够数据',
        },
    }