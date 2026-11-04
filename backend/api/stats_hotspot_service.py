from api.patrol_opinion_service import build_patrol_opinion_payload


def build_hotspot_payload(lookback_days, top_k, current_user, is_admin_checker, attach_hotspot_regions, logger=None):
    payload = build_patrol_opinion_payload(
        lookback_days=lookback_days,
        top_k=top_k,
        current_user=current_user,
        is_admin_checker=is_admin_checker,
        logger=logger,
    )
    attach_hotspot_regions(payload)
    payload['perf'] = {
        'cache_hit': False,
        'query_ms': 0.0,
        'geocode_ms': 0.0,
        'total_ms': 0.0,
        'source': 'database_patrol_opinion',
    }
    payload['ok'] = True
    return payload
