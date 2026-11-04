import os
import threading
import zipfile
from typing import Any, cast

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from services.auth import admin_required, login_required

from api.train_helpers import (
    _ALLOWED_WEIGHT_EXTENSIONS,
    _ALLOWED_ZIP_EXTENSIONS,
    _append_log,
    _is_allowed,
    _job_lock,
    _job_state,
    _now_iso,
    _parse_bool,
    _parse_int,
    _load_persisted_job,
    _persist_job,
    _run_training_job,
    _safe_extract_zip,
)
from api.train_route_services import (
    build_job_payload,
    build_job_state,
    ensure_training_roots,
    init_job_dataset,
    parse_training_options,
    resolve_data_yaml,
    resolve_weight_path,
)


train_bp = Blueprint('train_bp', __name__)


@train_bp.route('/config', methods=['GET'])
@login_required
def get_training_config():
    train_max_content_length = current_app.config.get('TRAIN_MAX_CONTENT_LENGTH')
    return jsonify({
        'ok': True,
        'limits': {
            'train_max_content_length': int(train_max_content_length) if isinstance(train_max_content_length, int) else None,
        },
        'accept': {
            'dataset_extensions': sorted(_ALLOWED_ZIP_EXTENSIONS),
            'weight_extensions': sorted(_ALLOWED_WEIGHT_EXTENSIONS),
        },
    })


@train_bp.route('/start', methods=['POST'])
@admin_required
def start_training():
    # Admin only: uploaded .pt weights and dataset YAML files can execute code when loaded.
    train_max_content_length = current_app.config.get('TRAIN_MAX_CONTENT_LENGTH')
    request_content_length = request.content_length or 0
    if isinstance(train_max_content_length, int) and train_max_content_length > 0:
        if request_content_length > train_max_content_length:
            limit_mb = round(train_max_content_length / (1024 * 1024), 2)
            return jsonify({
                'ok': False,
                'message': f'训练数据包过大，当前上限为 {limit_mb} MB。',
            }), 413

    dataset_zip = request.files.get('dataset_zip')
    if dataset_zip is None or not dataset_zip.filename:
        return jsonify({'ok': False, 'message': '请上传标注数据集 ZIP 文件（dataset_zip）。'}), 400
    if not _is_allowed(dataset_zip.filename, _ALLOWED_ZIP_EXTENSIONS):
        return jsonify({'ok': False, 'message': '数据集文件仅支持 .zip。'}), 400

    custom_weight = request.files.get('weight_file')
    if custom_weight and custom_weight.filename and not _is_allowed(custom_weight.filename, _ALLOWED_WEIGHT_EXTENSIONS):
        return jsonify({'ok': False, 'message': '权重文件仅支持 .pt。'}), 400

    with _job_lock:
        active_job_id = _job_state.get('active_job_id')
        if active_job_id:
            active_job = _job_state['jobs'].get(active_job_id, {})
            if active_job.get('status') in {'queued', 'running'}:
                return jsonify({
                    'ok': False,
                    'message': '当前已有训练任务在进行中，请稍后再试。',
                    'job_id': active_job_id,
                }), 409

    base_dir = current_app.config.get('BASE_DIR', os.getcwd())
    dataset_root, weights_root, runs_root = ensure_training_roots(base_dir)

    job_id, job_dataset_dir, dataset_name, dataset_zip_path = init_job_dataset(dataset_zip, dataset_root)

    try:
        _safe_extract_zip(dataset_zip_path, job_dataset_dir)
    except (zipfile.BadZipFile, ValueError) as error:
        return jsonify({'ok': False, 'message': f'数据集 ZIP 无法解压: {error}'}), 400

    try:
        yaml_relative, yaml_path = resolve_data_yaml(job_dataset_dir, request.form.get('data_yaml'))
    except ValueError as error:
        return jsonify({'ok': False, 'message': str(error)}), 400

    default_weight_path = current_app.config.get('YOLO_MODEL_PATH', os.path.join(base_dir, 'best.pt'))
    weight_path = resolve_weight_path(custom_weight, weights_root, job_id, base_dir, default_weight_path)
    if not os.path.exists(weight_path):
        return jsonify({'ok': False, 'message': f'未找到可用权重文件: {weight_path}'}), 400

    epochs, batch, imgsz, device, resume, run_name = parse_training_options(
        request.form,
        job_id,
        _parse_int,
        _parse_bool,
    )

    job_payload = build_job_payload(
        job_dataset_dir,
        yaml_path,
        weight_path,
        epochs,
        batch,
        imgsz,
        device,
        resume,
        run_name,
        runs_root,
    )

    with _job_lock:
        _job_state['jobs'][job_id] = build_job_state(
            job_id,
            dataset_name,
            yaml_relative,
            run_name,
            epochs,
            batch,
            imgsz,
            device,
            resume,
            _now_iso(),
        )
        _job_state['active_job_id'] = job_id

    _append_log(job_id, f'任务已创建: {job_id}')
    _append_log(job_id, '数据集上传并解压完成，准备启动训练线程。')
    _persist_job(job_id)

    app_obj = cast(Any, current_app)._get_current_object()

    thread = threading.Thread(
        target=_run_training_job,
        args=(app_obj, job_id, job_payload),
        daemon=True,
        name=f'train-job-{job_id[:8]}',
    )
    thread.start()

    return jsonify({
        'ok': True,
        'message': '训练任务已启动。',
        'job_id': job_id,
        'status': 'queued',
    })


@train_bp.route('/status/<job_id>', methods=['GET'])
@login_required
def get_training_status(job_id):
    with _job_lock:
        job = _job_state['jobs'].get(job_id)
    if not job:
        # Not in memory (e.g. after a restart): fall back to the persisted copy.
        job = _load_persisted_job(job_id)
    if not job:
        return jsonify({'ok': False, 'message': '训练任务不存在。'}), 404

    return jsonify({
        'ok': True,
        'job': {
            'job_id': job['job_id'],
            'status': job['status'],
            'created_at': job['created_at'],
            'started_at': job['started_at'],
            'completed_at': job['completed_at'],
            'error': job['error'],
            'meta': job['meta'],
            'result': job['result'],
            'logs': job['logs'][-40:],
            'is_active': _job_state.get('active_job_id') == job_id,
            'server_time': _now_iso(),
            'poll_interval_ms': 2500,
        },
    })


@train_bp.route('/status', methods=['GET'])
@login_required
def get_active_training_status():
    with _job_lock:
        job_id = _job_state.get('active_job_id')
        if not job_id:
            jobs = _job_state.get('jobs') or {}
            if jobs:
                latest_job = max(
                    jobs.values(),
                    key=lambda item: str(item.get('created_at') or ''),
                )
                job_id = latest_job.get('job_id')

    if not job_id:
        persisted_job = _load_persisted_job()
        job_id = persisted_job['job_id'] if persisted_job else None

    if not job_id:
        return jsonify({'ok': True, 'job': None})
    return get_training_status(job_id)
