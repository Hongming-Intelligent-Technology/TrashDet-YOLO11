import os
import threading
import uuid
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request

from api.detect_helpers import (
    _HAS_CV2,
    _normalize_ingest_detection,
    complete_task,
    create_detect_task,
    cv2,
    ensure_storage_dirs,
    fail_task,
    get_detection_dependency_report,
    get_detection_runtime_error,
    is_allowed_image,
    is_allowed_video,
    json_error,
    json_success,
    load_detector,
    lookup_address,
    logger,
    parse_bool,
    parse_geo_from_form,
    parse_int,
    parse_optional_float,
    read_uploaded_file,
    resolve_location,
    save_detect_items,
    save_uploaded_file,
)
from api.detect_route_services import (
    build_image_result_paths,
    ensure_image_size_with_cleanup,
    ensure_video_size_with_cleanup,
    parse_image_request,
    parse_ingest_payload,
    parse_video_request,
)
from database.db import db
from database.models import DetectTask, Robot
from services.auth import get_session_user as _get_session_user, is_admin_user as _is_admin_user


detect_bp = Blueprint('detect_bp', __name__)


def _resolve_task_owner_user_id(device_id=None):
    current_user = _get_session_user()
    if current_user:
        return current_user.id

    if device_id:
        robot = Robot.query.filter_by(device_id=device_id).first()
        if robot:
            return robot.owner_user_id

    return None


def _can_access_task(user, task):
    if not user:
        return False
    if _is_admin_user(user):
        return True
    return getattr(task, 'user_id', None) == getattr(user, 'id', None)


@detect_bp.route('/detect/dependencies', methods=['GET'])
def detect_dependencies():
    report = get_detection_dependency_report()
    return jsonify({'ok': True, **report})


@detect_bp.route('/detect/ingest', methods=['POST'])
def ingest_detection_result():
    payload = request.get_json(silent=True) or {}
    try:
        ingest_context = parse_ingest_payload(
            payload=payload,
            normalize_detection=_normalize_ingest_detection,
            parse_optional_float=parse_optional_float,
            resolve_location=resolve_location,
            parse_int=parse_int,
        )
    except ValueError as error:
        return jsonify({'ok': False, 'message': str(error)}), 400

    if not ingest_context['normalized_detections']:
        return json_success({
            'task_id': None,
            'inserted_items': 0,
            'skipped_items': ingest_context['skipped_count'],
            'recorded': False,
            'task': None,
        })

    task = create_detect_task(
        source_rel_path=ingest_context['source_rel_path'],
        result_rel_path=ingest_context['result_rel_path'],
        source_type=ingest_context['source_type'],
        lat=ingest_context['latitude'],
        lng=ingest_context['longitude'],
        location=ingest_context['location'],
        device_id=ingest_context['device_id'],
        user_id=_resolve_task_owner_user_id(ingest_context['device_id']),
    )

    try:
        save_detect_items(
            task,
            ingest_context['normalized_detections'],
            snapshot_rel_path=ingest_context['result_rel_path'],
            frame_index=ingest_context['frame_index'],
        )
        complete_task(task)
    except Exception as error:
        fail_task(task, error)
        logger.exception('解析服务入库失败 task_id=%s', task.id)
        return json_error(error, 500)

    return json_success({
        'task_id': task.id,
        'inserted_items': len(ingest_context['normalized_detections']),
        'skipped_items': ingest_context['skipped_count'],
        'recorded': True,
        'task': task.to_dict() if hasattr(task, 'to_dict') else {'id': task.id},
    })


# Allowance for multipart boundaries and the small form fields sent with the file.
_FORM_OVERHEAD_BYTES = 64 * 1024


def _reject_oversized_request(limit_key, default_limit, label):
    """413 response if the request body is larger than the file limit, before anything is read."""
    limit = current_app.config.get(limit_key, default_limit)
    if request.content_length and request.content_length > limit + _FORM_OVERHEAD_BYTES:
        return jsonify({'ok': False, 'message': f'{label}超过大小限制 ({limit // (1024 * 1024)} MB)'}), 413
    return None


@detect_bp.route("/detect", methods=["POST"])
def detect_image():
    oversized = _reject_oversized_request('IMAGE_MAX_CONTENT_LENGTH', 10 * 1024 * 1024, '图片文件')
    if oversized:
        return oversized

    dependency_error = get_detection_runtime_error(require_video=False)
    if dependency_error:
        return json_error(dependency_error, 503)

    ensure_storage_dirs()

    uploaded_file = read_uploaded_file(['image', 'file'])
    try:
        image_context = parse_image_request(
            form_data=request.form,
            uploaded_file=uploaded_file,
            parse_geo_from_form=parse_geo_from_form,
            is_allowed_image=is_allowed_image,
        )
    except ValueError as error:
        return jsonify({'ok': False, 'message': str(error)}), 400

    resolved_location = resolve_location(image_context['latitude'], image_context['longitude'])

    file_name, source_abs_path, source_rel_path = save_uploaded_file(uploaded_file)

    image_max = current_app.config.get('IMAGE_MAX_CONTENT_LENGTH', 10 * 1024 * 1024)
    if not ensure_image_size_with_cleanup(source_abs_path, image_max):
        return jsonify({"ok": False, "message": f"图片文件超过大小限制 ({image_max // (1024 * 1024)} MB)"}), 413

    result_abs_path, result_rel_path = build_image_result_paths(current_app.config['RESULT_DIR'], file_name)

    task = None

    try:
        detector = load_detector()
        if not detector:
            raise RuntimeError("YOLO 模型未就绪")

        conf_thres = current_app.config.get("YOLO_CONF_THRESHOLD", 0.25)
        detections = detector.analyze_uploaded_waste_image(
            source_abs_path,
            save_result=True,
            result_path=result_abs_path,
            conf_thres=conf_thres
        )

        if not detections:
            return json_success({
                'result': [],
                'annotated_image_path': result_rel_path,
                'recorded': False,
                'task': None,
            })

        task = create_detect_task(
            source_rel_path=source_rel_path,
            result_rel_path=result_rel_path,
            source_type=image_context['source_type'],
            lat=image_context['latitude'],
            lng=image_context['longitude'],
            location=resolved_location,
            device_id=image_context['device_id'],
            user_id=_resolve_task_owner_user_id(image_context['device_id']),
        )

        detection_results = save_detect_items(task, detections, snapshot_rel_path=result_rel_path, frame_index=0)

        complete_task(task)

        return json_success({
            "result": detection_results,
            "annotated_image_path": result_rel_path,
            "recorded": True,
            "task": task.to_dict() if hasattr(task, 'to_dict') else {"id": task.id}
        })

    except (FileNotFoundError, PermissionError, IOError, RuntimeError, TimeoutError, ValueError) as error:
        if task is not None:
            fail_task(task, error)
            logger.exception("图片检测流程失败，task_id=%s", task.id)
        else:
            logger.exception("图片检测流程失败（未创建任务）")
        return json_error(error, 500)


def _process_video_background(app, task_id, source_abs_path, conf_thres, frame_step, max_frames, result_dir):
    """后台线程执行视频检测，通过 task_id 轮询 /detect/video/status/<task_id> 查询进度。"""
    with app.app_context():
        task = db.session.get(DetectTask, task_id)
        if not task:
            logger.error('视频后台任务找不到 task_id=%s', task_id)
            return
        cap = None
        try:
            detector = load_detector()
            if not detector:
                raise RuntimeError('YOLO 模型未就绪')

            cap = cv2.VideoCapture(source_abs_path)
            if not cap.isOpened():
                raise RuntimeError('无法打开视频文件')

            frame_index = 0
            processed = 0
            hit_frames = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                frame_index += 1
                if frame_index % frame_step != 0:
                    continue

                processed += 1
                detections, annotated_frame = detector.analyze_realtime_camera_stream(frame, conf_thres=conf_thres)
                if not detections:
                    if processed >= max_frames:
                        break
                    continue

                hit_frames += 1
                snap_name = f"{task.id}_frame_{frame_index}_{uuid.uuid4().hex[:8]}.jpg"
                snap_abs_path = os.path.join(result_dir, snap_name)
                snap_rel_path = f"static/results/{snap_name}"
                if not cast(Any, cv2).imwrite(snap_abs_path, annotated_frame):
                    raise IOError(f"快照保存失败: {snap_abs_path}")

                if not task.result_path:
                    task.result_path = snap_rel_path

                save_detect_items(task, detections, snapshot_rel_path=snap_rel_path, frame_index=frame_index)

                if processed >= max_frames:
                    break

            complete_task(task)
            logger.info('视频后台任务完成 task_id=%s frames_processed=%s hit_frames=%s',
                        task_id, processed, hit_frames)

        except (FileNotFoundError, PermissionError, IOError, RuntimeError, TimeoutError, ValueError) as error:
            fail_task(task, error)
            logger.exception('视频后台任务失败 task_id=%s', task_id)
        finally:
            if cap is not None:
                cap.release()


@detect_bp.route('/detect/video', methods=['POST'])
def detect_video():
    oversized = _reject_oversized_request('VIDEO_MAX_CONTENT_LENGTH', 200 * 1024 * 1024, '视频文件')
    if oversized:
        return oversized

    dependency_error = get_detection_runtime_error(require_video=True)
    if dependency_error:
        return json_error(dependency_error, 503)

    if not _HAS_CV2:
        return json_error('OpenCV 未安装，暂不可使用视频检测', 503)

    ensure_storage_dirs()

    uploaded_file = read_uploaded_file(['video', 'file'])
    try:
        video_context = parse_video_request(
            form_data=request.form,
            uploaded_file=uploaded_file,
            parse_geo_from_form=parse_geo_from_form,
            parse_int=parse_int,
            is_allowed_video=is_allowed_video,
        )
    except ValueError as error:
        return jsonify({'ok': False, 'message': str(error)}), 400

    _, source_abs_path, source_rel_path = save_uploaded_file(uploaded_file)

    # 视频文件大小校验
    video_max = current_app.config.get('VIDEO_MAX_CONTENT_LENGTH', 200 * 1024 * 1024)
    if not ensure_video_size_with_cleanup(source_abs_path, video_max):
        return jsonify({'ok': False, 'message': f'视频文件超过大小限制 ({video_max // (1024 * 1024)} MB)'}), 413

    resolved_location = resolve_location(video_context['latitude'], video_context['longitude'])
    conf_thres = current_app.config.get('YOLO_CONF_THRESHOLD', 0.25)
    result_dir = current_app.config['RESULT_DIR']

    task = create_detect_task(
        source_rel_path=source_rel_path,
        result_rel_path=None,
        source_type='video',
        lat=video_context['latitude'],
        lng=video_context['longitude'],
        location=resolved_location,
        device_id=video_context['device_id'],
        user_id=_resolve_task_owner_user_id(video_context['device_id']),
    )

    # 立即返回 task_id，后台线程异步处理视频
    app = cast(Any, current_app)._get_current_object()
    t = threading.Thread(
        target=_process_video_background,
        args=(app, task.id, source_abs_path, conf_thres, video_context['frame_step'], video_context['max_frames'], result_dir),
        daemon=True
    )
    t.start()

    return json_success({
        'task_id': task.id,
        'status': 'PROCESSING',
        'status_url': f'/api/detect/video/status/{task.id}',
        'task': {'id': task.id, 'source_type': task.source_type}
    })


@detect_bp.route('/detect/video/status/<int:task_id>', methods=['GET'])
def detect_video_status(task_id):
    task = db.session.get(DetectTask, task_id)
    if not task:
        return json_error('任务不存在', 404)

    current_user = _get_session_user()
    if not current_user:
        return json_error('请先登录', 401)
    if not _can_access_task(current_user, task):
        return json_error('无权限访问该任务', 403)

    payload = {
        'task_id': task.id,
        'status': task.status,
        'source_type': task.source_type,
    }
    if task.status == 'DONE':
        payload['annotated_image_path'] = task.result_path
        payload['result'] = [
            {
                'label': item.label,
                'confidence': f"{item.confidence * 100:.2f}%" if item.confidence else None,
                'bbox': [item.x1, item.y1, item.x2, item.y2],
                'frame_index': item.frame_index,
                'snapshot_path': item.snapshot_path,
            }
            for item in cast(Any, task).items
        ]
    elif task.status == 'FAILED':
        payload['error'] = task.error_msg

    return json_success(payload)
