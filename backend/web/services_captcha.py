import base64
import io
import math
import random
import string
import time

from flask import current_app, session

from .utils import _normalize_secret

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    Image = None
    ImageDraw = None
    ImageFilter = None


def _is_captcha_enforced():
    # Captcha is bypassed during tests to keep existing test payloads stable.
    return bool(current_app.config.get('CAPTCHA_ENABLED', True)) and not current_app.config.get('TESTING', False)


def _get_captcha_length():
    length = int(current_app.config.get('CAPTCHA_LENGTH', 4))
    return max(4, min(length, 8))


def _get_captcha_expire_seconds():
    expires = int(current_app.config.get('CAPTCHA_EXPIRE_SECONDS', 180))
    return max(60, min(expires, 600))


def _get_captcha_max_failures():
    max_failures = int(current_app.config.get('CAPTCHA_MAX_FAILURES', 3))
    return max(1, min(max_failures, 10))


def _get_captcha_cooldown_seconds():
    cooldown = int(current_app.config.get('CAPTCHA_COOLDOWN_SECONDS', 5))
    return max(1, min(cooldown, 60))


def _generate_captcha_code(length):
    alphabet = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
    return ''.join(random.choice(alphabet) for _ in range(length))


def _build_captcha_image_data(code):
    if Image is None or ImageDraw is None:
        raise RuntimeError('图形验证码依赖 Pillow，请先安装 Pillow。')

    width = 132
    height = 44
    image = Image.new('RGB', (width, height), (245, 251, 247))
    draw = ImageDraw.Draw(image)

    for _ in range(6):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=(160, 185, 170), width=1)

    for _ in range(60):
        draw.point((random.randint(0, width - 1), random.randint(0, height - 1)), fill=(130, 160, 145))

    for index, char in enumerate(code):
        x = 14 + index * 26 + random.randint(-2, 2)
        y = 10 + random.randint(-2, 3)
        draw.text((x, y), char, fill=(35, 82, 66))

    if ImageFilter is not None:
        image = image.filter(ImageFilter.SMOOTH)

    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def _issue_captcha_payload():
    code = _generate_captcha_code(_get_captcha_length())
    captcha_id = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(24))
    expires_in = _get_captcha_expire_seconds()
    expires_at = int(time.time() + expires_in)

    session['captcha'] = {
        'id': captcha_id,
        'code': code,
        'expires_at': expires_at,
    }
    session.modified = True

    return {
        'captcha_id': captcha_id,
        'image_data': _build_captcha_image_data(code),
        'expires_in': expires_in,
    }


def _format_captcha_meta(meta):
    meta = meta or {}
    payload = {
        'force_refresh': bool(meta.get('force_refresh', False)),
        'cooldown_seconds': int(meta.get('cooldown_seconds', 0) or 0),
    }
    refreshed = meta.get('captcha') or {}
    if refreshed:
        payload['captcha_id'] = refreshed.get('captcha_id', '')
        payload['image_data'] = refreshed.get('image_data', '')
        payload['expires_in'] = int(refreshed.get('expires_in', 0) or 0)
    return payload


def _verify_captcha_payload(payload):
    if not _is_captcha_enforced():
        return True, '', {}

    guard_state = session.get('captcha_guard') or {}
    now = time.time()
    cooldown_until = float(guard_state.get('cooldown_until') or 0)
    if cooldown_until > now:
        remaining = max(1, int(math.ceil(cooldown_until - now)))
        return False, f'操作过于频繁，请 {remaining} 秒后再试', {
            'force_refresh': False,
            'cooldown_seconds': remaining,
        }

    captcha_text = _normalize_secret(payload.get('captcha_text')).upper()
    captcha_id = _normalize_secret(payload.get('captcha_id'))
    if not captcha_text or not captcha_id:
        return False, '请输入图形验证码', {
            'force_refresh': False,
            'cooldown_seconds': 0,
        }

    captcha_state = session.get('captcha') or {}
    expected_id = str(captcha_state.get('id') or '')
    expected_code = str(captcha_state.get('code') or '').upper()
    expires_at = int(captcha_state.get('expires_at') or 0)

    if not expected_id or not expected_code:
        refreshed = _issue_captcha_payload()
        return False, '验证码已失效，请刷新后重试', {
            'force_refresh': True,
            'cooldown_seconds': 0,
            'captcha': refreshed,
        }
    if expected_id != captcha_id:
        refreshed = _issue_captcha_payload()
        return False, '验证码不匹配，请刷新后重试', {
            'force_refresh': True,
            'cooldown_seconds': 0,
            'captcha': refreshed,
        }
    if time.time() > expires_at:
        session.pop('captcha', None)
        refreshed = _issue_captcha_payload()
        return False, '验证码已过期，请刷新后重试', {
            'force_refresh': True,
            'cooldown_seconds': 0,
            'captcha': refreshed,
        }
    if captcha_text != expected_code:
        max_failures = _get_captcha_max_failures()
        cooldown_seconds = _get_captcha_cooldown_seconds()
        failures = int(guard_state.get('failures') or 0) + 1
        meta = {
            'force_refresh': False,
            'cooldown_seconds': 0,
        }

        if failures >= max_failures:
            guard_state['failures'] = 0
            guard_state['cooldown_until'] = now + cooldown_seconds
            refreshed = _issue_captcha_payload()
            meta = {
                'force_refresh': True,
                'cooldown_seconds': cooldown_seconds,
                'captcha': refreshed,
            }
            session['captcha_guard'] = guard_state
            session.modified = True
            return False, f'验证码连续错误次数过多，请 {cooldown_seconds} 秒后重试', meta

        guard_state['failures'] = failures
        guard_state['cooldown_until'] = 0
        session['captcha_guard'] = guard_state
        session.modified = True
        return False, '验证码错误', meta

    session.pop('captcha', None)
    guard_state['failures'] = 0
    guard_state['cooldown_until'] = 0
    session['captcha_guard'] = guard_state
    session.modified = True
    return True, '', {}
