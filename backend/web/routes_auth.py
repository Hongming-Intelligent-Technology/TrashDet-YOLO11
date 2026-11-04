from flask import current_app, flash, jsonify, redirect, request, session

from .services_auth import (
    AuthValidationError,
    apply_login_session,
    apply_logout_session,
    authenticate_user,
    ensure_login_input,
    ensure_register_input,
    parse_login_form_payload,
    parse_login_json_payload,
    parse_register_form_payload,
    parse_register_json_payload,
)
from .blueprint import web_bp
from .helpers import (
    DEFAULT_LOGIN_NEXT,
    _captcha_error_response,
    _create_user,
    _find_user_by_username,
    _is_captcha_enforced,
    _issue_captcha_payload,
    _normalize_secret,
    _render_main_spa,
    _serialize_user,
    _validate_next_path,
    _verify_captcha_payload,
    _get_current_user,
)


@web_bp.route('/api/web/session', methods=['GET'])
def get_session_state():
    return jsonify({
        'ok': True,
        'user': _serialize_user(_get_current_user()),
    })


@web_bp.route('/api/web/captcha', methods=['GET'])
def get_captcha_json():
    if not _is_captcha_enforced():
        return jsonify({
            'ok': True,
            'captcha_enabled': False,
            'captcha_id': '',
            'image_data': '',
            'expires_in': 0,
        })

    try:
        payload = _issue_captcha_payload()
    except RuntimeError as error:
        return jsonify({'ok': False, 'message': str(error)}), 500

    return jsonify({
        'ok': True,
        'captcha_enabled': True,
        **payload,
    })


@web_bp.route('/api/web/login', methods=['POST'])
def login_json():
    payload = request.get_json(silent=True) or {}
    username, password, next_path = parse_login_json_payload(
        payload,
        normalize_secret=_normalize_secret,
        validate_next_path=_validate_next_path,
    )

    try:
        ensure_login_input(username, password)
    except AuthValidationError as error:
        return jsonify({'ok': False, 'message': error.message}), error.status_code

    captcha_ok, captcha_error, captcha_meta = _verify_captcha_payload(payload)
    if not captcha_ok:
        return _captcha_error_response(captcha_error, 400, captcha_meta)

    try:
        user = authenticate_user(username, password, _find_user_by_username)
    except AuthValidationError as error:
        return jsonify({'ok': False, 'message': error.message}), error.status_code

    apply_login_session(session, user)

    return jsonify({
        'ok': True,
        'message': '登录成功',
        'next': next_path or DEFAULT_LOGIN_NEXT,
        'user': _serialize_user(user),
    })


@web_bp.route('/api/web/register', methods=['POST'])
def register_json():
    payload = request.get_json(silent=True) or {}
    username, password, confirm_password, security_code, organization = parse_register_json_payload(
        payload,
        normalize_secret=_normalize_secret,
    )

    try:
        ensure_register_input(
            username,
            password,
            confirm_password,
            security_code,
            organization,
            _find_user_by_username,
        )
    except AuthValidationError as error:
        return jsonify({'ok': False, 'message': error.message}), error.status_code

    captcha_ok, captcha_error, captcha_meta = _verify_captcha_payload(payload)
    if not captcha_ok:
        return _captcha_error_response(captcha_error, 400, captcha_meta)

    _create_user(username, password, security_code, organization=organization)

    return jsonify({
        'ok': True,
        'message': '注册成功，请登录',
    })


@web_bp.route('/api/web/logout', methods=['POST'])
def logout_json():
    apply_logout_session(session)
    return jsonify({'ok': True, 'message': '已退出登录'})


@web_bp.route('/login', methods=['GET', 'POST'])
def login_page_compat():
    if request.method == 'GET':
        return _render_main_spa(next_path=_validate_next_path(request.args.get('next')))

    username, password, next_path = parse_login_form_payload(
        request.form,
        normalize_secret=_normalize_secret,
        validate_next_path=_validate_next_path,
        default_next=DEFAULT_LOGIN_NEXT,
    )

    try:
        ensure_login_input(username, password)
    except AuthValidationError as error:
        flash(error.message, 'error')
        return redirect('/login')

    # Same captcha check as the JSON login, so this form route cannot bypass it.
    captcha_ok, captcha_error, _captcha_meta = _verify_captcha_payload(request.form)
    if not captcha_ok:
        flash(captcha_error, 'error')
        return redirect('/login')

    try:
        user = authenticate_user(username, password, _find_user_by_username)
    except AuthValidationError as error:
        flash(error.message, 'error')
        return redirect('/login')

    apply_login_session(session, user)
    return redirect(next_path)


@web_bp.route('/register', methods=['GET', 'POST'])
def register_page_compat():
    if request.method == 'GET':
        return _render_main_spa()

    username, password, confirm_password, security_code, organization = parse_register_form_payload(
        request.form,
        normalize_secret=_normalize_secret,
    )

    try:
        ensure_register_input(
            username,
            password,
            confirm_password,
            security_code,
            organization,
            _find_user_by_username,
        )
    except AuthValidationError as error:
        return error.message, error.status_code

    _create_user(username, password, security_code, organization=organization)

    if current_app.config.get('TESTING', False):
        return '注册成功，请登录', 200

    flash('注册成功，请登录', 'success')
    return redirect('/login')


@web_bp.route('/logout', methods=['POST'])
def logout_page_compat():
    apply_logout_session(session)
    return redirect('/login')
