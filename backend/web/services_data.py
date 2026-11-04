def build_pagination_payload(pagination):
    return {
        'page': pagination.page,
        'pages': pagination.pages,
        'total': pagination.total,
        'has_prev': pagination.has_prev,
        'has_next': pagination.has_next,
        'prev_num': pagination.prev_num,
        'next_num': pagination.next_num,
    }


def _build_paginated_collection_payload(pagination, can_delete, key, items):
    return {
        'ok': True,
        key: items,
        'pagination': build_pagination_payload(pagination),
        'can_delete': bool(can_delete),
    }


def build_tasks_payload(pagination, can_delete, serialize_task):
    items = [serialize_task(task) for task in pagination.items]
    return _build_paginated_collection_payload(
        pagination=pagination,
        can_delete=can_delete,
        key='tasks',
        items=items,
    )


def build_items_payload(pagination, can_delete, serialize_item_row):
    items = [serialize_item_row(item) for item in pagination.items]
    return _build_paginated_collection_payload(
        pagination=pagination,
        can_delete=can_delete,
        key='items',
        items=items,
    )


def build_task_detail_payload(task, can_delete, serialize_task, serialize_item):
    return {
        'ok': True,
        'task': serialize_task(task),
        'items': [serialize_item(item) for item in task.items],
        'can_delete': bool(can_delete),
    }
