class AuthValidationError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = str(message)
        self.status_code = int(status_code)


def parse_login_json_payload(payload, normalize_secret, validate_next_path):
    data = payload or {}
    username = normalize_secret(data.get('username'))
    password = normalize_secret(data.get('password'))
    next_path = validate_next_path(data.get('next'))
    return username, password, next_path


def parse_register_json_payload(payload, normalize_secret):
    data = payload or {}
    username = normalize_secret(data.get('username'))
    password = normalize_secret(data.get('password'))
    confirm_password = normalize_secret(data.get('confirm_password'))
    security_code = normalize_secret(data.get('security_code'))
    organization = normalize_secret(data.get('organization'))
    return username, password, confirm_password, security_code, organization


def parse_login_form_payload(form_data, normalize_secret, validate_next_path, default_next):
    username = normalize_secret(form_data.get('username'))
    password = normalize_secret(form_data.get('password'))
    next_path = validate_next_path(form_data.get('next')) or default_next
    return username, password, next_path


def parse_register_form_payload(form_data, normalize_secret):
    username = normalize_secret(form_data.get('username'))
    password = normalize_secret(form_data.get('password'))
    confirm_password = normalize_secret(form_data.get('confirm_password'))
    security_code = normalize_secret(form_data.get('security_code'))
    organization = normalize_secret(form_data.get('organization'))
    return username, password, confirm_password, security_code, organization


def ensure_login_input(username, password):
    if not username or not password:
        raise AuthValidationError('用户名和密码不能为空', 400)


def authenticate_user(username, password, find_user_by_username):
    user = find_user_by_username(username)
    if not user or not user.check_password(password):
        raise AuthValidationError('用户名或密码错误', 400)
    return user


def ensure_register_input(username, password, confirm_password, security_code, organization, find_user_by_username):
    if not username or not password or not confirm_password or not security_code or not organization:
        raise AuthValidationError('请完整填写注册信息', 400)
    if len(username) < 3 or len(username) > 50:
        raise AuthValidationError('用户名长度需在 3-50 个字符之间', 400)
    if len(password) < 6:
        raise AuthValidationError('密码至少 6 位', 400)
    if password != confirm_password:
        raise AuthValidationError('两次输入的密码不一致', 400)
    if len(organization) > 120:
        raise AuthValidationError('所属单位长度不能超过 120 个字符', 400)
    if find_user_by_username(username):
        raise AuthValidationError('用户名已存在，请更换', 409)


def apply_login_session(session_obj, user):
    session_obj.clear()
    session_obj['user_id'] = user.id


def apply_logout_session(session_obj):
    session_obj.clear()
