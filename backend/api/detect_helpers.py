import logging
import os
import threading
import time
import uuid
from datetime import datetime

import requests
from flask import current_app, jsonify, request

from database.db import db
from database.models import DetectItem, DetectTask
from inference import yolo_detector as yolo_detector_module
from inference.yolo_detector import YOLODetector

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    class _Cv2Stub:
        def imwrite(self, *_args, **_kwargs):
            return False

    cv2 = _Cv2Stub()
    _HAS_CV2 = False


logger = logging.getLogger(__name__)

_detector = None
_detector_lock = threading.Lock()
DEFAULT_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
_DEPENDENCY_INSTALL_HINTS = {
    'ultralytics': 'pip install ultralytics',
    'opencv-python': 'pip install opencv-python',
}

# Nominatim requires <= 1 request/second.
_nominatim_lock = threading.Lock()
_nominatim_last_call_ts = 0.0
_NOMINATIM_MIN_INTERVAL = 1.1


def get_detection_dependency_report():
    missing = []
    install_commands = []
    image_ready = True
    video_ready = True

    if getattr(yolo_detector_module, 'YOLO', None) is None:
        image_ready = False
        video_ready = False
        missing.append('ultralytics')
        install_commands.append(_DEPENDENCY_INSTALL_HINTS['ultralytics'])

    if not _HAS_CV2:
        video_ready = False
        missing.append('opencv-python')
        install_commands.append(_DEPENDENCY_INSTALL_HINTS['opencv-python'])

    return {
        'ready': image_ready and video_ready,
        'missing': missing,
        'install_commands': install_commands,
        'capabilities': {
            'image_detection': image_ready,
            'video_detection': video_ready,
        },
    }


def log_detection_dependency_report(logger_obj=None):
    logger_ref = logger_obj or logger
    report = get_detection_dependency_report()
    if report['ready']:
        logger_ref.info('检测依赖检查通过：图片检测与视频检测均可用。')
        return

    missing_text = ', '.join(report['missing'])
    command_text = ' ; '.join(report['install_commands']) if report['install_commands'] else '无'
    logger_ref.warning(
        '检测依赖未完全就绪，缺少: %s; 图片检测可用=%s, 视频检测可用=%s; 安装建议: %s',
        missing_text,
        report['capabilities']['image_detection'],
        report['capabilities']['video_detection'],
        command_text,
    )


def get_detection_runtime_error(require_video=False):
    # Preserve existing tests that mock detector internals without full dependencies.
    if current_app.config.get('TESTING', False):
        return None

    report = get_detection_dependency_report()
    capability_key = 'video_detection' if require_video else 'image_detection'
    if report['capabilities'][capability_key]:
        return None

    scenario = '视频检测' if require_video else '图片检测'
    missing_text = '、'.join(report['missing']) or '必要依赖'
    command_text = ' ; '.join(report['install_commands'])
    if command_text:
        return f'{scenario}依赖未就绪，缺少 {missing_text}。可执行: {command_text}'
    return f'{scenario}依赖未就绪，缺少 {missing_text}。'


def parse_optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value, default_value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


def parse_bool(value, default_value=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        return default_value
    if isinstance(value, (int, float)):
        return value != 0
    return default_value


def is_allowed_image(filename):
    allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', DEFAULT_IMAGE_EXTENSIONS)
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def is_allowed_video(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in VIDEO_EXTENSIONS


def load_detector():
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                model_path = current_app.config.get('YOLO_MODEL_PATH', 'best.pt')
                conf_thres = current_app.config.get('YOLO_CONF_THRESHOLD', 0.25)
                left_half_only = parse_bool(current_app.config.get('DETECT_LEFT_HALF_ONLY', False), False)
                camera_timeout_ms = current_app.config.get('CAMERA_TIMEOUT_MS', 3000)
                try:
                    _detector = YOLODetector(
                        model_path=model_path,
                        default_conf_thres=conf_thres,
                        left_half_only=left_half_only,
                        camera_timeout_ms=camera_timeout_ms,
                    )
                except (FileNotFoundError, PermissionError, RuntimeError, ImportError, ValueError) as error:
                    logger.error('YOLO 初始化失败: %s', error)
                    _detector = None
    return _detector


def ensure_storage_dirs():
    static_root = os.path.join(current_app.root_path, 'static')
    upload_dir = current_app.config.get('UPLOAD_DIR', os.path.join(static_root, 'uploads'))
    result_dir = current_app.config.get('RESULT_DIR', os.path.join(static_root, 'results'))
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)


def create_detect_task(source_rel_path, result_rel_path=None, source_type='image', lat=None, lng=None,
                       location='未知地点', device_id=None, user_id=None):
    task = DetectTask(
        source_type=source_type,
        source_path=source_rel_path,
        result_path=result_rel_path,
        status='PENDING',
        user_id=user_id,
        latitude=lat,
        longitude=lng,
        location=location,
        device_id=device_id,
        created_at=datetime.now(),
    )
    db.session.add(task)
    db.session.commit()
    return task


def save_detect_items(task, detections, snapshot_rel_path=None, frame_index=None):
    now = datetime.now()
    result_items = []
    for detection in detections:
        x1, y1, x2, y2 = [int(coord) for coord in detection['bbox']]
        detect_item = DetectItem(
            task_id=task.id,
            label=detection['label'],
            confidence=float(detection['confidence']),
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            area=max(0, int((x2 - x1) * (y2 - y1))),
            handle_state='NEW',
            frame_index=frame_index,
            snapshot_path=snapshot_rel_path,
            captured_at=now,
        )
        db.session.add(detect_item)

        result_items.append({
            'class_name': detection['label'],
            'confidence': f"{detection['confidence'] * 100:.2f}%",
            'bbox': [x1, y1, x2, y2],
            'frame_index': frame_index,
            'snapshot_path': snapshot_rel_path,
        })

    return result_items


def fail_task(task, error):
    db.session.rollback()
    task.status = 'FAILED'
    task.error_msg = str(error)
    db.session.commit()


def json_error(message, status_code=500):
    return jsonify({'ok': False, 'message': str(message)}), status_code


def json_success(payload):
    body = {'ok': True, 'status': 'success'}
    body.update(payload)
    return jsonify(body)


def parse_geo_from_form(form_data):
    latitude = parse_optional_float(form_data.get('latitude'))
    longitude = parse_optional_float(form_data.get('longitude'))
    return latitude, longitude


def resolve_location(latitude, longitude):
    if latitude is None or longitude is None:
        return '未知地点'
    return lookup_address(latitude, longitude)


def save_uploaded_file(uploaded_file):
    file_extension = os.path.splitext(uploaded_file.filename)[1].lower()
    file_name = f"{uuid.uuid4().hex}{file_extension}"
    source_abs_path = os.path.join(current_app.config['UPLOAD_DIR'], file_name)
    source_rel_path = f"static/uploads/{file_name}"
    uploaded_file.save(source_abs_path)
    return file_name, source_abs_path, source_rel_path


def read_uploaded_file(field_names):
    for field_name in field_names:
        file_obj = request.files.get(field_name)
        if file_obj is not None:
            return file_obj
    return None


def complete_task(task, status='DONE'):
    task.status = status
    db.session.commit()


def _normalize_bbox(raw_bbox):
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            return [int(float(raw_bbox[0])), int(float(raw_bbox[1])), int(float(raw_bbox[2])), int(float(raw_bbox[3]))]
        except (TypeError, ValueError):
            return None
    return None


def _normalize_ingest_detection(raw_item):
    if not isinstance(raw_item, dict):
        return None

    label = str(raw_item.get('label') or raw_item.get('class_name') or '').strip()
    if not label:
        return None

    confidence = raw_item.get('confidence', raw_item.get('score', 0.0))
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))

    bbox = _normalize_bbox(raw_item.get('bbox'))
    if bbox is None:
        x1 = raw_item.get('x1')
        y1 = raw_item.get('y1')
        x2 = raw_item.get('x2')
        y2 = raw_item.get('y2')
        bbox = _normalize_bbox([x1, y1, x2, y2])
    if bbox is None:
        return None

    return {
        'label': label,
        'confidence': confidence,
        'bbox': bbox,
    }


def _nominatim_rate_limit():
    global _nominatim_last_call_ts
    with _nominatim_lock:
        now = time.time()
        wait_time = _NOMINATIM_MIN_INTERVAL - (now - _nominatim_last_call_ts)
        if wait_time > 0:
            time.sleep(wait_time)
        _nominatim_last_call_ts = time.time()


def lookup_address(lat, lng):
    if lat is None or lng is None:
        return '未知地点'

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return f'坐标： {lat}, {lng} (超出有效范围)'

    try:
        _nominatim_rate_limit()
        url = f'https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=10&addressdetails=1'
        headers = {
            'User-Agent': 'TrashDet/2.0 (trash-detection-robot-system)'
        }

        geo_response = requests.get(url, headers=headers, timeout=5)
        if geo_response.status_code == 200:
            geo_payload = geo_response.json()
            resolved_address = geo_payload.get('display_name', '未知地点')
            return resolved_address
        return f'坐标： {lat}, {lng} (无法解析地址)'

    except Exception:
        logger.exception('地址解析失败')
        return f'坐标： {lat}, {lng} (解析地址失败)'
