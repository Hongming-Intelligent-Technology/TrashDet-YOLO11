def is_api_or_static_path(path):
    return str(path).startswith('api/') or str(path).startswith('static/')


def build_not_found_payload():
    return {
        'ok': False,
        'code': 404,
        'name': 'Not Found',
        'message': 'Not Found',
    }


def can_delete_result_for_page(current_user, is_admin_user):
    return bool(is_admin_user(current_user))
