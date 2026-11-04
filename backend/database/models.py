from datetime import datetime
from typing import TYPE_CHECKING, Any
from sqlalchemy import Double, String, event
from database.db import db
from flask_login import UserMixin
import werkzeug.security as security

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    security_code = db.Column(db.String(255), nullable=False)
    organization = db.Column(db.String(120), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='user', server_default='user')

    if TYPE_CHECKING:
        def __init__(
            self,
            *,
            username: str,
            password_hash: str = '',
            security_code: str = '',
            organization: str | None = None,
            role: str = 'user',
            **kwargs: Any,
        ) -> None: ...

    @staticmethod
    def _hash_value(raw_value):
        return security.generate_password_hash(str(raw_value))

    @staticmethod
    def _check_hash(hashed_value, raw_value):
        return security.check_password_hash(hashed_value, str(raw_value))

    @staticmethod
    def _normalize_secret(raw_value):
        return str(raw_value or '').strip()

    def set_password(self, password):
        self.password_hash = self._hash_value(self._normalize_secret(password))

    def check_password(self, password):
        return self._check_hash(self.password_hash, self._normalize_secret(password))

    def set_security_code(self, security_code):
        self.security_code = self._hash_value(self._normalize_secret(security_code))

    def check_security_code(self, security_code):
        return self._check_hash(self.security_code, self._normalize_secret(security_code))


class DetectTask(db.Model):
    __tablename__ = 'detection_tasks'

    id = db.Column(db.Integer, primary_key=True)
    source_type = db.Column(db.String(20))
    source_path = db.Column(db.String(255))
    result_path = db.Column(db.String(255), nullable=True)
    device_id = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='PENDING')
    error_msg = db.Column(db.Text, nullable=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL', name='fk_detection_tasks_user_id'),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    latitude = db.Column(Double, nullable=True, index=True)
    longitude = db.Column(Double, nullable=True)

    items = db.relationship('DetectItem', backref='task', lazy=True, cascade='all, delete-orphan')

    if TYPE_CHECKING:
        def __init__(
            self,
            *,
            source_type: str = 'image',
            source_path: str = '',
            result_path: str | None = None,
            device_id: str | None = None,
            location: str | None = None,
            status: str = 'PENDING',
            error_msg: str | None = None,
            user_id: int | None = None,
            created_at: datetime | None = None,
            latitude: float | None = None,
            longitude: float | None = None,
            **kwargs: Any,
        ) -> None: ...

    def to_dict(self):
        return {
            'id': self.id,
            'source_type': self.source_type,
            'source_path': self.source_path,
            'result_path': self.result_path,
            'device_id': self.device_id,
            'location': self.location,
            'status': self.status,
            'error_msg': self.error_msg,
            'user_id': self.user_id,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class DetectItem(db.Model):
    __tablename__ = 'detection_items'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey('detection_tasks.id', ondelete='CASCADE', name='fk_detection_items_task_id'),
        nullable=False,
        index=True,
    )
    label = db.Column(db.String(50), index=True)
    confidence = db.Column(db.Float)
    x1 = db.Column(db.Integer)
    y1 = db.Column(db.Integer)
    x2 = db.Column(db.Integer)
    y2 = db.Column(db.Integer)
    area = db.Column(db.Integer)
    handle_state = db.Column(db.String(20), default='NEW')
    frame_index = db.Column(db.Integer, nullable=True)
    snapshot_path = db.Column(db.String(255), nullable=True)
    captured_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    if TYPE_CHECKING:
        def __init__(
            self,
            *,
            task_id: int,
            label: str,
            confidence: float,
            x1: int,
            y1: int,
            x2: int,
            y2: int,
            area: int,
            handle_state: str = 'NEW',
            frame_index: int | None = None,
            snapshot_path: str | None = None,
            captured_at: datetime | None = None,
            **kwargs: Any,
        ) -> None: ...


class OpsLog(db.Model):
    __tablename__ = 'operation_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL', name='fk_operation_logs_user_id'))
    action = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.now)


class TrainJob(db.Model):
    """Persisted copy of a training job, so status survives a server restart."""

    __tablename__ = 'train_jobs'

    id = db.Column(db.String(32), primary_key=True)
    status = db.Column(db.String(20), nullable=False, default='queued')
    created_at = db.Column(db.String(32))
    started_at = db.Column(db.String(32))
    completed_at = db.Column(db.String(32))
    error = db.Column(db.Text)
    meta_json = db.Column(db.Text)
    result_json = db.Column(db.Text)
    logs_json = db.Column(db.Text)


class RobotPatrolTask(db.Model):
    __tablename__ = 'robot_patrol_tasks'
    __table_args__ = (
        db.Index('ix_robot_patrol_tasks_robot_id_status', 'robot_id', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    robot_id = db.Column(db.Integer, db.ForeignKey('robots.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    inspection_area = db.Column(db.Text, nullable=False)
    planned_path = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='PLANNED', nullable=False)
    current_waypoint_index = db.Column(db.Integer, default=0, nullable=False)
    created_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL', name='fk_robot_patrol_tasks_created_by_user_id'),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    if TYPE_CHECKING:
        def __init__(
            self,
            *,
            robot_id: int,
            name: str,
            inspection_area: str,
            planned_path: str | None = None,
            status: str = 'PLANNED',
            current_waypoint_index: int = 0,
            created_by_user_id: int | None = None,
            created_at: datetime | None = None,
            **kwargs: Any,
        ) -> None: ...


class Robot(db.Model):
    __tablename__ = 'robots'

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100))
    status = db.Column(db.String(20), default='OFFLINE')
    ip_address = db.Column(db.String(50))
    owner_user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL', name='fk_robots_owner_user_id'),
        nullable=True,
        index=True,
    )

    current_lat = db.Column(Double, nullable=True)
    current_lng = db.Column(Double, nullable=True)

    target_lat = db.Column(Double, nullable=True)
    target_lng = db.Column(Double, nullable=True)

    last_heartbeat = db.Column(db.DateTime, default=datetime.now)
    next_command = db.Column(db.String(100), default='IDLE')

    battery = db.Column(db.Integer, default=100)
    config = db.Column(db.JSON, default=lambda: {"confidence_threshold": 0.5, "active": True})
    created_at = db.Column(db.DateTime, default=datetime.now)
    patrol_tasks = db.relationship('RobotPatrolTask', backref='robot', lazy=True, cascade='all, delete-orphan')

    if TYPE_CHECKING:
        def __init__(
            self,
            *,
            device_id: str,
            name: str | None = None,
            status: str = 'OFFLINE',
            ip_address: str | None = None,
            owner_user_id: int | None = None,
            current_lat: float | None = None,
            current_lng: float | None = None,
            target_lat: float | None = None,
            target_lng: float | None = None,
            last_heartbeat: datetime | None = None,
            next_command: str | None = 'IDLE',
            battery: int = 100,
            config: dict[str, Any] | None = None,
            created_at: datetime | None = None,
            **kwargs: Any,
        ) -> None: ...


def _truncate_string_columns(mapper, _connection, target):
    """Cut str values to their column length before writing.

    MySQL in strict mode rejects over-long values and fails the whole request;
    values from devices (ingest payloads, custom commands) are not length-checked.
    """
    for column in mapper.columns:
        length = getattr(column.type, 'length', None)
        if not isinstance(column.type, String) or not length:
            continue
        value = getattr(target, column.key, None)
        if isinstance(value, str) and len(value) > length:
            setattr(target, column.key, value[:length])


event.listen(db.Model, 'before_insert', _truncate_string_columns, propagate=True)
event.listen(db.Model, 'before_update', _truncate_string_columns, propagate=True)
