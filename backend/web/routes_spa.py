from flask import jsonify, redirect, request

from .blueprint import web_bp
from .helpers import _delete_task_with_items, _get_current_user, _is_admin_user, _render_main_spa, page_login_required
from .services_spa import build_not_found_payload, can_delete_result_for_page, is_api_or_static_path


@web_bp.route('/')
@web_bp.route('/result')
@web_bp.route('/result/<int:task_id>')
@web_bp.route('/upload')
@web_bp.route('/stats')
@web_bp.route('/robot')
@web_bp.route('/robot/<int:robot_id>')
@web_bp.route('/users')
@page_login_required
def show_protected_spa_page(**_route_params):
    return _render_main_spa()


@web_bp.route('/result/<int:task_id>/delete', methods=['POST'])
@page_login_required
def delete_result_page_compat(task_id):
    current_user = _get_current_user()
    if not can_delete_result_for_page(current_user, _is_admin_user):
        return redirect(f'/result/{task_id}')

    _delete_task_with_items(task_id)
    return redirect('/result')


@web_bp.route('/<path:path>')
def catch_all_spa(path):
    if is_api_or_static_path(path):
        return jsonify(build_not_found_payload()), 404
    return _render_main_spa()
