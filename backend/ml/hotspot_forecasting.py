from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import math

try:
    from services.hotspot_search_engine import HotspotSearchEngine
except Exception:
    HotspotSearchEngine = None


DEFAULT_FORECAST_DAYS = 1
DEFAULT_GRID_SIZE = 0.001
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_TOP_K = 6
DEFAULT_MIN_CONFIDENCE = 0.15
DEFAULT_MIN_CONFIDENCE_DETECTIONS = 3


def _created_at_to_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return None


def _safe_float(value, default_value=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default_value


def _build_service_events(records, lookback_days, as_of_day):
    cutoff_day = as_of_day - timedelta(days=lookback_days - 1)
    events = []
    tasks_used = 0
    detections_used = 0

    for index, record in enumerate(records):
        latitude = _record_value(record, 'latitude')
        longitude = _record_value(record, 'longitude')
        created_at_raw = _record_value(record, 'created_at')
        created_at = _created_at_to_datetime(created_at_raw)
        if created_at is None:
            continue

        event_day = created_at.date()
        if event_day < cutoff_day:
            continue
        if not _is_valid_coordinate(latitude, longitude):
            continue

        latitude_value = _safe_float(latitude)
        longitude_value = _safe_float(longitude)
        if latitude_value is None or longitude_value is None:
            continue

        detection_count = max(_safe_int(_record_value(record, 'detection_count'), 0), 0)
        task_count = max(_safe_int(_record_value(record, 'task_count'), 1), 0)
        if detection_count <= 0:
            continue

        label = str(_record_value(record, 'label') or 'unknown').strip() or 'unknown'
        volume = float(detection_count) + float(task_count) * 0.5
        events.append({
            'id': index + 1,
            'longitude': longitude_value,
            'latitude': latitude_value,
            'timestamp': created_at.isoformat(),
            'waste_type': label,
            'volume': max(0.1, volume),
        })
        tasks_used += task_count
        detections_used += detection_count

    return events, tasks_used, detections_used


def _build_hotspot_forecast_via_service(records, lookback_days, top_k, grid_size, forecast_days):
    if HotspotSearchEngine is None:
        return None

    as_of_day = datetime.now().date()
    events, tasks_used, detections_used = _build_service_events(
        records=records,
        lookback_days=lookback_days,
        as_of_day=as_of_day,
    )

    if not events:
        return {
            'generated_at': datetime.now().isoformat(),
            'grid_size': grid_size,
            'lookback_days': lookback_days,
            'forecast_days': forecast_days,
            'summary': {
                'cells_analyzed': 0,
                'tasks_used': 0,
                'detections_used': 0,
            },
            'chart_data': {
                'labels': [],
                'values': [],
            },
            'hotspots': [],
            'recommendations': ['历史垃圾点位不足，暂时无法生成热点预测。'],
        }

    try:
        engine = HotspotSearchEngine()
        engine.fit(events)
        hotspots = engine.build_hotspots(top_k=top_k)
    except Exception:
        return None

    return {
        'generated_at': datetime.now().isoformat(),
        'grid_size': grid_size,
        'lookback_days': lookback_days,
        'forecast_days': forecast_days,
        'summary': {
            'cells_analyzed': len(hotspots),
            'tasks_used': tasks_used,
            'detections_used': detections_used,
        },
        'chart_data': {
            'labels': [f"热点 {item.get('rank', index + 1)}" for index, item in enumerate(hotspots)],
            'values': [item.get('predicted_count', 0) for item in hotspots],
        },
        'hotspots': hotspots,
        'recommendations': _build_recommendations(hotspots),
    }


def _build_hotspot_forecast_legacy(records, lookback_days, grid_size, top_k, forecast_days):
    as_of_day = datetime.now().date()
    cells = _aggregate_grid_cells(
        records=records,
        lookback_days=lookback_days,
        grid_size=grid_size,
        as_of_day=as_of_day
    )
    if not cells:
        return _build_empty_forecast_payload(
            grid_size=grid_size,
            lookback_days=lookback_days,
            forecast_days=forecast_days,
        )

    scored_cells = [
        _score_grid_cell(cell=cell, as_of_day=as_of_day, lookback_days=lookback_days, forecast_days=forecast_days)
        for cell in cells.values()
    ]
    scored_cells.sort(key=lambda item: (item['predicted_count'], item['recent_7_avg'], item['total_detections']), reverse=True)

    confidence_filtered = [
        item for item in scored_cells
        if _passes_confidence_filter(item, lookback_days)
    ]
    candidate_cells = confidence_filtered if confidence_filtered else scored_cells

    top_cells = candidate_cells[:top_k]
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
            'confidence': round(item['confidence'], 3),
            'task_count': item['task_count'],
            'dominant_labels': item['dominant_labels'],
            'last_seen_at': item['last_seen_at'].isoformat() if item['last_seen_at'] else None,
            'history': item['history'],
            'reason': _build_hotspot_reason(item),
        })

    return {
        'generated_at': datetime.now().isoformat(),
        'grid_size': grid_size,
        'lookback_days': lookback_days,
        'forecast_days': forecast_days,
        'summary': {
            'cells_analyzed': len(cells),
            'tasks_used': sum(cell['task_count'] for cell in cells.values()),
            'detections_used': sum(cell['total_detections'] for cell in cells.values()),
        },
        'chart_data': {
            'labels': [f"热点 {item['rank']}" for item in hotspots],
            'values': [item['predicted_count'] for item in hotspots],
        },
        'hotspots': hotspots,
        'recommendations': _build_recommendations(hotspots),
    }


def build_hotspot_forecast(records, lookback_days=DEFAULT_LOOKBACK_DAYS, grid_size=DEFAULT_GRID_SIZE,
                           top_k=DEFAULT_TOP_K, forecast_days=DEFAULT_FORECAST_DAYS):
    normalized_lookback = max(7, int(lookback_days or DEFAULT_LOOKBACK_DAYS))
    normalized_top_k = max(1, int(top_k or DEFAULT_TOP_K))
    normalized_horizon = max(1, int(forecast_days or DEFAULT_FORECAST_DAYS))
    normalized_grid_size = max(0.001, float(grid_size or DEFAULT_GRID_SIZE))
    payload = _build_hotspot_forecast_legacy(
        records=records,
        lookback_days=normalized_lookback,
        grid_size=normalized_grid_size,
        top_k=normalized_top_k,
        forecast_days=normalized_horizon,
    )
    if payload.get('hotspots'):
        return payload

    # Keep service path only as a fallback for sparse/edge data.
    service_payload = _build_hotspot_forecast_via_service(
        records=records,
        lookback_days=normalized_lookback,
        top_k=normalized_top_k,
        grid_size=normalized_grid_size,
        forecast_days=normalized_horizon,
    )
    if service_payload is not None:
        return service_payload

    return payload


def _aggregate_grid_cells(records, lookback_days, grid_size, as_of_day):
    cutoff_day = as_of_day - timedelta(days=lookback_days - 1)
    cells = {}

    for record in records:
        latitude = _record_value(record, 'latitude')
        longitude = _record_value(record, 'longitude')
        created_at = _record_value(record, 'created_at')
        if not _is_valid_coordinate(latitude, longitude) or created_at is None:
            continue

        event_day = _to_event_day(created_at)
        if event_day is None:
            continue
        if event_day < cutoff_day:
            continue

        label = _record_value(record, 'label')
        detection_count = _safe_int(_record_value(record, 'detection_count'), 0)
        task_count = _safe_int(_record_value(record, 'task_count'), 1)
        if detection_count <= 0:
            continue
        if label:
            labels = [label] * detection_count
        else:
            labels = []

        grid_lat = _grid_floor(latitude, grid_size)
        grid_lng = _grid_floor(longitude, grid_size)
        grid_id = f"{grid_lat:.4f},{grid_lng:.4f}"
        center_lat = round(grid_lat + (grid_size / 2.0), 6)
        center_lng = round(grid_lng + (grid_size / 2.0), 6)
        cell = cells.setdefault(grid_id, {
            'grid_id': grid_id,
            'sum_lat': 0.0,
            'sum_lng': 0.0,
            'count': 0,
            'weight_total': 0.0,
            'center_lat': center_lat,
            'center_lng': center_lng,
            'daily_counts': defaultdict(int),
            'label_counter': Counter(),
            'task_count': 0,
            'total_detections': 0,
            'last_seen_at': None,
        })
        cell['daily_counts'][event_day] += detection_count
        cell['label_counter'].update(labels)
        cell['task_count'] += max(task_count, 0)
        cell['total_detections'] += detection_count
        weight = max(float(detection_count), 1.0)
        cell['sum_lat'] += float(latitude) * weight
        cell['sum_lng'] += float(longitude) * weight
        cell['count'] += 1
        cell['weight_total'] += weight
        if cell['last_seen_at'] is None or created_at > cell['last_seen_at']:
            cell['last_seen_at'] = created_at

    return cells


def _score_grid_cell(cell, as_of_day, lookback_days, forecast_days):
    window_days = [as_of_day - timedelta(days=offset) for offset in range(lookback_days - 1, -1, -1)]
    counts = [int(cell['daily_counts'].get(day, 0)) for day in window_days]
    recent_3_avg = _average(counts[-3:])
    recent_7_avg = _average(counts[-7:])
    overall_avg = _average(counts)
    wma_3 = _weighted_moving_average(counts, 3)
    wma_7 = _weighted_moving_average(counts, 7)
    wma_14 = _weighted_moving_average(counts, 14)
    today_count = counts[-1] if counts else 0
    previous_3_avg = _average(counts[-6:-3]) if len(counts) >= 6 else 0.0
    weekday_baseline = _weekday_average(cell['daily_counts'], as_of_day)
    active_days = sum(1 for value in counts if value > 0)
    confidence = float(active_days) / float(max(lookback_days, 1))
    recency_days = (as_of_day - cell['last_seen_at'].date()).days if cell['last_seen_at'] else lookback_days
    recency_factor = 1.0 / (1.0 + max(recency_days, 0))
    momentum = recent_3_avg - previous_3_avg
    horizon_factor = _smoothed_horizon_factor(forecast_days)

    centroid_weight = float(cell.get('weight_total', 0.0) or 0.0)
    if centroid_weight > 0:
        centroid_lat = round(cell['sum_lat'] / centroid_weight, 6)
        centroid_lng = round(cell['sum_lng'] / centroid_weight, 6)
    elif cell.get('count', 0) > 0:
        centroid_lat = round(cell['sum_lat'] / float(cell['count']), 6)
        centroid_lng = round(cell['sum_lng'] / float(cell['count']), 6)
    else:
        centroid_lat = cell['center_lat']
        centroid_lng = cell['center_lng']

    predicted_count = max(
        0.0,
        (
            wma_3 * 0.48 +
            wma_7 * 0.30 +
            wma_14 * 0.22 +
            max(momentum, -wma_3) * 0.20 +
            weekday_baseline * 0.12 +
            today_count * 0.10 * recency_factor
        ) * horizon_factor * (0.65 + 0.35 * confidence)
    )
    raw_score = (
        predicted_count * (0.70 + 0.30 * confidence)
        + (today_count * 0.25)
        + (recent_7_avg * 0.20)
        + recency_factor
    )

    return {
        'grid_id': cell['grid_id'],
        'center_lat': centroid_lat,
        'center_lng': centroid_lng,
        'predicted_count': predicted_count,
        'raw_score': raw_score,
        'today_count': today_count,
        'recent_7_avg': recent_7_avg,
        'overall_avg': overall_avg,
        'active_days': active_days,
        'confidence': confidence,
        'task_count': cell['task_count'],
        'total_detections': cell['total_detections'],
        'dominant_labels': [label for label, _ in cell['label_counter'].most_common(3)],
        'last_seen_at': cell['last_seen_at'],
        'history': _build_history(cell['daily_counts'], as_of_day),
    }


def _build_history(daily_counts, as_of_day, days=7):
    labels = []
    values = []
    for offset in range(days - 1, -1, -1):
        day = as_of_day - timedelta(days=offset)
        labels.append(day.strftime('%m-%d'))
        values.append(int(daily_counts.get(day, 0)))
    return {
        'labels': labels,
        'values': values,
    }


def _build_empty_forecast_payload(grid_size, lookback_days, forecast_days):
    return {
        'generated_at': datetime.now().isoformat(),
        'grid_size': grid_size,
        'lookback_days': lookback_days,
        'forecast_days': forecast_days,
        'summary': {
            'cells_analyzed': 0,
            'tasks_used': 0,
            'detections_used': 0,
        },
        'chart_data': {
            'labels': [],
            'values': [],
        },
        'hotspots': [],
        'recommendations': ['历史垃圾点位不足，暂时无法生成热点预测。'],
    }


def _build_hotspot_reason(item):
    labels = '、'.join(item['dominant_labels']) if item['dominant_labels'] else '混合垃圾'
    confidence_text = f"置信度 {round(item.get('confidence', 0.0) * 100)}%"
    if item['today_count'] > 0:
        return f"近 24 小时仍有 {item['today_count']} 个垃圾目标，{labels}出现更集中（{confidence_text}）。"
    if item['recent_7_avg'] >= item['overall_avg']:
        return f"近 7 天活跃度高于长期均值，{labels}在该区域复现概率较高（{confidence_text}）。"
    return f"该网格在历史窗口内持续有检测记录，建议优先巡检 {labels}（{confidence_text}）。"


def _build_recommendations(hotspots):
    if not hotspots:
        return ['当前还没有足够的历史数据来生成巡检建议。']

    recommendations = []
    top_hotspot = hotspots[0]
    labels = '、'.join(top_hotspot['dominant_labels']) if top_hotspot['dominant_labels'] else '混合垃圾'
    recommendations.append(
        f"优先巡检热点 1，风险分 {top_hotspot['risk_score']}，预测未来 24 小时约有 {top_hotspot['predicted_count']} 个目标。"
    )
    recommendations.append(
        f"热点 1 的主导垃圾类型为 {labels}，可针对性准备对应抓取与分类策略。"
    )
    if len(hotspots) > 1:
        total_predicted = round(sum(item['predicted_count'] for item in hotspots[:3]), 2)
        recommendations.append(
            f"前 3 个热点区域合计预测目标数约为 {total_predicted}，适合作为机器人优先巡检路线。"
        )
    return recommendations


def _normalize_risk_score(raw_score, max_raw_score):
    if raw_score <= 0 or max_raw_score <= 0:
        return 0
    return min(100, max(30, int(round((raw_score / max_raw_score) * 100))))


def _passes_confidence_filter(item, lookback_days):
    confidence = float(item.get('confidence', 0.0) or 0.0)
    total_detections = int(item.get('total_detections', 0) or 0)
    if confidence >= DEFAULT_MIN_CONFIDENCE:
        return True
    if total_detections >= DEFAULT_MIN_CONFIDENCE_DETECTIONS:
        return True
    # 对于窗口较小的场景，允许略低置信度通过，避免全部被过滤。
    return confidence >= (1.0 / float(max(lookback_days, 1)))


def _weighted_moving_average(values, window):
    if not values:
        return 0.0
    size = max(1, min(int(window), len(values)))
    recent = list(values[-size:])
    weights = list(range(1, size + 1))
    weighted_sum = sum(value * weight for value, weight in zip(recent, weights))
    return float(weighted_sum) / float(sum(weights))


def _smoothed_horizon_factor(forecast_days):
    horizon = max(1.0, float(forecast_days))
    # 使用对数平滑预测跨度，避免 forecast_days 放大过快。
    return 1.0 + (math.log1p(horizon) * 0.35)


def _weekday_average(daily_counts, as_of_day):
    values = [
        count for day, count in daily_counts.items()
        if day.weekday() == as_of_day.weekday()
    ]
    return _average(values)


def _average(values):
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _record_value(record, key, default=None):
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _to_event_day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _grid_floor(value, grid_size):
    return math.floor(float(value) / grid_size) * grid_size


def _is_valid_coordinate(latitude, longitude):
    if latitude is None or longitude is None:
        return False
    return -90.0 <= float(latitude) <= 90.0 and -180.0 <= float(longitude) <= 180.0

