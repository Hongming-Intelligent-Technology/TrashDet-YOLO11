import json
import logging
import os
import threading
import zipfile
from datetime import datetime
from pathlib import Path

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

from database.db import db
from database.models import TrainJob


logger = logging.getLogger(__name__)

_ALLOWED_ZIP_EXTENSIONS = {'zip'}
_ALLOWED_WEIGHT_EXTENSIONS = {'pt'}
_MAX_LOG_LINES = 200

_job_lock = threading.Lock()
_job_state = {
    'active_job_id': None,
    'jobs': {},
}


def _now_iso():
    return datetime.now().isoformat(timespec='seconds')


def _is_allowed(filename, extensions):
    if not filename or '.' not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in extensions


def _parse_int(value, default_value, minimum=1, maximum=100000):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default_value
    return max(minimum, min(parsed, maximum))


def _parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _append_log(job_id, message):
    with _job_lock:
        job = _job_state['jobs'].get(job_id)
        if not job:
            return
        log_line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        job['logs'].append(log_line)
        if len(job['logs']) > _MAX_LOG_LINES:
            job['logs'] = job['logs'][-_MAX_LOG_LINES:]


def _persist_job(job_id):
    """Write the in-memory job state to the train_jobs table.

    Must run inside an app context. Failures are logged but never interrupt training.
    """
    with _job_lock:
        job = _job_state['jobs'].get(job_id)
        snapshot = json.loads(json.dumps(job, default=str)) if job else None
    if snapshot is None:
        return

    try:
        row = db.session.get(TrainJob, job_id) or TrainJob(id=job_id)
        row.status = snapshot['status']
        row.created_at = snapshot['created_at']
        row.started_at = snapshot['started_at']
        row.completed_at = snapshot['completed_at']
        row.error = snapshot['error']
        row.meta_json = json.dumps(snapshot['meta'], ensure_ascii=False)
        row.result_json = json.dumps(snapshot['result'], ensure_ascii=False)
        row.logs_json = json.dumps(snapshot['logs'][-_MAX_LOG_LINES:], ensure_ascii=False)
        db.session.add(row)
        db.session.commit()
    except Exception:
        logger.exception('训练任务状态持久化失败 job_id=%s', job_id)
        try:
            db.session.rollback()
        except Exception:
            pass


def _load_persisted_job(job_id=None):
    """Return a job dict from the database (latest job if job_id is None), or None."""
    try:
        if job_id:
            row = db.session.get(TrainJob, job_id)
        else:
            row = TrainJob.query.order_by(TrainJob.created_at.desc()).first()
    except Exception:
        logger.exception('读取训练任务失败 job_id=%s', job_id)
        return None
    if row is None:
        return None

    def _loads(raw, default):
        try:
            return json.loads(raw) if raw else default
        except ValueError:
            return default

    return {
        'job_id': row.id,
        'status': row.status,
        'created_at': row.created_at,
        'started_at': row.started_at,
        'completed_at': row.completed_at,
        'error': row.error,
        'logs': _loads(row.logs_json, []),
        'result': _loads(row.result_json, {}),
        'meta': _loads(row.meta_json, {}),
    }


def _safe_extract_zip(zip_path, target_dir):
    with zipfile.ZipFile(zip_path, 'r') as archive:
        for member in archive.infolist():
            member_path = Path(target_dir, member.filename)
            resolved_target = Path(target_dir).resolve()
            resolved_member = member_path.resolve()
            if not str(resolved_member).startswith(str(resolved_target)):
                raise ValueError('ZIP 包含非法路径，已拒绝解压。')
        archive.extractall(target_dir)


def _run_training_job(app, job_id, payload):
    yaml_path = payload['yaml_path']
    weight_path = payload['weight_path']
    epochs = payload['epochs']
    batch = payload['batch']
    imgsz = payload['imgsz']
    device = payload['device']
    run_name = payload['run_name']
    resume = payload['resume']
    project_dir = payload['project_dir']

    with app.app_context():
        try:
            _append_log(job_id, '准备加载 YOLO 模型...')
            if YOLO is None:
                raise RuntimeError('未安装 ultralytics，无法启动训练。')

            if not os.path.exists(weight_path):
                raise FileNotFoundError(f'权重文件不存在: {weight_path}')
            if not os.path.exists(yaml_path):
                raise FileNotFoundError(f'数据配置文件不存在: {yaml_path}')

            model = YOLO(weight_path)
            _append_log(job_id, f'模型加载成功: {weight_path}')
            _append_log(job_id, f'训练数据: {yaml_path}')
            _append_log(job_id, f'参数 epochs={epochs}, batch={batch}, imgsz={imgsz}, device={device}, resume={resume}')

            with _job_lock:
                job = _job_state['jobs'][job_id]
                job['status'] = 'running'
                job['started_at'] = _now_iso()
            _persist_job(job_id)

            train_kwargs = {
                'data': yaml_path,
                'epochs': epochs,
                'batch': batch,
                'imgsz': imgsz,
                'project': project_dir,
                'name': run_name,
                'device': device,
                'exist_ok': True,
                'resume': resume,
            }

            result = model.train(**train_kwargs)
            save_dir = str(getattr(result, 'save_dir', ''))

            with _job_lock:
                job = _job_state['jobs'][job_id]
                job['status'] = 'completed'
                job['completed_at'] = _now_iso()
                job['result'] = {
                    'save_dir': save_dir,
                    'weights_hint': os.path.join(save_dir, 'weights', 'best.pt') if save_dir else '',
                }

            _append_log(job_id, f'训练完成，输出目录: {save_dir or "未知"}')
        except Exception as error:
            logger.exception('训练任务失败: %s', error)
            with _job_lock:
                job = _job_state['jobs'].get(job_id)
                if job:
                    job['status'] = 'failed'
                    job['completed_at'] = _now_iso()
                    job['error'] = str(error)
            _append_log(job_id, f'训练失败: {error}')
        finally:
            with _job_lock:
                if _job_state['active_job_id'] == job_id:
                    _job_state['active_job_id'] = None
            _persist_job(job_id)
