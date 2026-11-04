from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests

_QT_IMPORT_ERROR = None
try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QDoubleSpinBox,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSplitter,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    QT_BINDING = "PySide6"
except ImportError:
    try:
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QPixmap
        from PyQt6.QtWidgets import (
            QApplication,
            QFileDialog,
            QDoubleSpinBox,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QHeaderView,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QSplitter,
            QStatusBar,
            QTableWidget,
            QTableWidgetItem,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
        QT_BINDING = "PyQt6"
    except ImportError as exc:
        QT_BINDING = None
        _QT_IMPORT_ERROR = exc
        Qt = None
        QMainWindow = object


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 每次移动指令对应的位移量（度，约 1.1 m）
_STEP_DEG = 0.00001
# 快速移动倍率
_FAST_MULTIPLIER = 3.0
# 慢速移动倍率
_SLOW_MULTIPLIER = 0.4
# 自动导航每拍步进比例（越小越平滑）
_NAV_STEP_RATIO = 0.08
# 导航到达阈值（度）
_NAV_ARRIVE_THRESHOLD = 0.00003
# 电量每次心跳消耗
_BATTERY_DRAIN_PER_BEAT = 0.02

# 服务器端支持的所有控制命令（与 robot_api.py 保持一致）
CONTROL_COMMANDS = {
    'FORWARD', 'BACK', 'LEFT', 'RIGHT', 'STOP',
    'PICK_TRASH', 'RESET', 'PAUSE', 'RESUME',
    'SLOW_FORWARD', 'FAST_FORWARD', 'SPIN_LEFT', 'SPIN_RIGHT',
    'HOLD_POSITION', 'CANCEL_NAVIGATION', 'RETURN_HOME', 'DOCK',
}

# 终端别名 -> 服务器命令
_CMD_ALIAS = {
    'f':        'FORWARD',
    'b':        'BACK',
    'l':        'LEFT',
    'r':        'RIGHT',
    's':        'STOP',
    'sf':       'SLOW_FORWARD',
    'ff':       'FAST_FORWARD',
    'sl':       'SPIN_LEFT',
    'sr':       'SPIN_RIGHT',
    'pick':     'PICK_TRASH',
    'hold':     'HOLD_POSITION',
    'home':     'RETURN_HOME',
    'dock':     'DOCK',
    'pause':    'PAUSE',
    'resume':   'RESUME',
    'reset':    'RESET',
    'cancelnav': 'CANCEL_NAVIGATION',
}

_HELP_TEXT = """
╔══════════════════════════════════════════════════════════╗
║              TrashDet 机器人交互式模拟器                 ║
╠══════════════════════════════════════════════════════════╣
║  移动控制                                                ║
║    f  / forward          向前移动                        ║
║    b  / back             向后移动                        ║
║    l  / left             向左转                          ║
║    r  / right            向右转                          ║
║    sf / slow_forward     慢速前进                        ║
║    ff / fast_forward     快速前进                        ║
║    sl / spin_left        原地左转                        ║
║    sr / spin_right       原地右转                        ║
║    s  / stop             停止                            ║
║    hold                  保持当前位置                    ║
║                                                          ║
║  任务指令                                                ║
║    pick                  抓取垃圾                        ║
║    home / return_home    返回基地                        ║
║    dock                  停靠充电                        ║
║    pause / resume        暂停 / 恢复                     ║
║    reset                 重置机器人                      ║
║    cancelnav             取消当前导航                    ║
║                                                          ║
║  导航                                                    ║
║    nav <lat> <lng>       导航到指定坐标                  ║
║      例: nav 30.512 114.305                              ║
║                                                          ║
║  模拟器控制                                              ║
║    status                显示当前机器人状态              ║
║    battery <0-100>       手动设置电量                    ║
║    heading <0-359>       手动设置朝向（度，0=北）        ║
║    interval <秒>         修改心跳间隔                    ║
║    help / ?              显示本帮助                      ║
║    quit / q / exit       退出模拟器                      ║
╚══════════════════════════════════════════════════════════╝
"""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _parse_json(resp):
    try:
        return resp.json()
    except Exception:
        return {}


def _post_json(url, payload, timeout=5):
    resp = requests.post(url, json=payload, timeout=timeout)
    return resp, _parse_json(resp)


def _normalize_server_url(raw):
    server = (raw or '').strip()
    if not server:
        return 'http://127.0.0.1:5000'
    if '://' not in server:
        server = f'http://{server}'
    return server.rstrip('/')


def _clamp_lat(v):
    return max(-90.0, min(90.0, v))


def _clamp_lng(v):
    return max(-180.0, min(180.0, v))


def _heading_to_delta(heading_deg, step):
    """将朝向角度（0=北，顺时针）和步长转换为 (dlat, dlng)。"""
    rad = math.radians(heading_deg)
    dlat = math.cos(rad) * step
    dlng = math.sin(rad) * step
    return dlat, dlng


def _ts():
    return time.strftime('%H:%M:%S')


def _info(msg):
    print(f'\r[{_ts()}] {msg}')
    print('> ', end='', flush=True)


def _warn(msg):
    _info(f'⚠  {msg}')


# ---------------------------------------------------------------------------
# 机器人模拟器核心
# ---------------------------------------------------------------------------

class RobotSimulator:
    def __init__(self, server, device_id, name, lat, lng, battery, interval):
        self.server = _normalize_server_url(server)
        self.device_id = device_id
        self.name = name
        self.interval = interval

        # 可变状态（所有修改须持有 _lock）
        self._lock = threading.Lock()
        self._lat = lat
        self._lng = lng
        self._home_lat = lat
        self._home_lng = lng
        self._battery = float(battery)
        self._heading = 0.0        # 朝向（度，0=北，顺时针）
        self._status = 'ONLINE'
        self._paused = False
        self._moving = None        # 当前持续运动模式，None 表示静止
        self._nav_target = None    # (target_lat, target_lng) 或 None
        self._server_cmd = 'IDLE'  # 上次服务器下发的指令
        self._db_id = None         # 服务器数据库中的 robot.id（用于 /control /navigate）
        self._stop_event = threading.Event()

        # URL 缩写
        self._heartbeat_url = f'{self.server}/api/robot/heartbeat'
        self._register_url  = f'{self.server}/api/robot/register'
        self._control_url   = f'{self.server}/api/robot/control'
        self._navigate_url  = f'{self.server}/api/robot/navigate'
        self._list_url      = f'{self.server}/api/robot/list'

    # ------------------------------------------------------------------
    # 内部状态读写
    # ------------------------------------------------------------------

    def _get_state(self):
        with self._lock:
            return (self._lat, self._lng, self._battery,
                    self._heading, self._status, self._nav_target, self._moving)

    def _set_pos(self, lat, lng):
        with self._lock:
            self._lat = _clamp_lat(lat)
            self._lng = _clamp_lng(lng)

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    def start(self):
        """注册设备（如未注册）并启动后台心跳线程。"""
        if not self._ensure_registered():
            return False
        self._fetch_db_id()
        t = threading.Thread(target=self._heartbeat_loop, daemon=True, name='heartbeat')
        t.start()
        return True

    def stop(self):
        self._stop_event.set()

    # ------------------------------------------------------------------
    # 注册 & 获取数据库 ID
    # ------------------------------------------------------------------

    def _ensure_registered(self):
        print(f'[{_ts()}] 连接服务器 {self.server} ...')
        try:
            resp, body = _post_json(
                self._heartbeat_url,
                {'device_id': self.device_id, 'lat': self._lat, 'lng': self._lng,
                 'battery': int(self._battery), 'status': 'ONLINE'},
                timeout=5
            )
            if resp.status_code == 403 or not body.get('ok'):
                print(f'[{_ts()}] 设备未注册，正在注册 {self.device_id} ...')
                _, reg = _post_json(
                    f'{self.server}/api/robot/register_device',
                    {'device_id': self.device_id, 'name': self.name},
                    timeout=5
                )
                if reg.get('ok'):
                    if reg.get('robot_id') is not None:
                        with self._lock:
                            self._db_id = reg.get('robot_id')
                    print(f'[{_ts()}] 注册成功')
                else:
                    print(f'[{_ts()}] 注册失败: {reg}')
                    return False
            else:
                print(f'[{_ts()}] 设备已存在，直接连接')
        except requests.exceptions.RequestException as e:
            print(f'[{_ts()}] 无法连接到服务器: {e}')
            return False
        return True

    def _fetch_db_id(self):
        """从 /api/robot/list 获取本机的数据库 ID，用于下发控制命令。"""
        try:
            resp = requests.get(self._list_url, timeout=5)
            body = _parse_json(resp)
            if body.get('ok'):
                for robot in body.get('robots') or []:
                    if robot.get('device_id') == self.device_id:
                        with self._lock:
                            self._db_id = robot.get('id')
                        print(f'[{_ts()}] 获取数据库 ID: {self._db_id}')
                        return
        except Exception:
            pass
        _warn('未能获取数据库 ID，控制命令将尝试用 device_id 代替')

    # ------------------------------------------------------------------
    # 位置模拟
    # ------------------------------------------------------------------

    def _apply_movement(self, mode):
        """根据运动模式更新位置和朝向，不持锁调用。"""
        with self._lock:
            heading = self._heading
            lat = self._lat
            lng = self._lng

        if mode == 'FORWARD':
            step = _STEP_DEG
        elif mode == 'FAST_FORWARD':
            step = _STEP_DEG * _FAST_MULTIPLIER
        elif mode == 'SLOW_FORWARD':
            step = _STEP_DEG * _SLOW_MULTIPLIER
        elif mode == 'BACK':
            step = -_STEP_DEG
        elif mode == 'LEFT':
            with self._lock:
                self._heading = (heading - 10) % 360
            return
        elif mode == 'RIGHT':
            with self._lock:
                self._heading = (heading + 10) % 360
            return
        elif mode == 'SPIN_LEFT':
            with self._lock:
                self._heading = (heading - 20) % 360
            return
        elif mode == 'SPIN_RIGHT':
            with self._lock:
                self._heading = (heading + 20) % 360
            return
        else:
            return

        dlat, dlng = _heading_to_delta(heading, step)
        with self._lock:
            self._lat = _clamp_lat(lat + dlat)
            self._lng = _clamp_lng(lng + dlng)

    def _apply_navigation(self):
        """自动导航：每拍向目标靠近一步。"""
        with self._lock:
            if self._nav_target is None:
                return
            tlat, tlng = self._nav_target
            lat, lng = self._lat, self._lng

        dist = math.sqrt((tlat - lat) ** 2 + (tlng - lng) ** 2)
        if dist <= _NAV_ARRIVE_THRESHOLD:
            with self._lock:
                self._nav_target = None
                self._moving = None
            _info(f'已到达目标坐标 ({tlat:.6f}, {tlng:.6f})')
            return

        # 朝目标角度移动
        target_heading = math.degrees(math.atan2(tlng - lng, tlat - lat)) % 360
        step = min(dist * _NAV_STEP_RATIO, _STEP_DEG * _FAST_MULTIPLIER)
        dlat, dlng = _heading_to_delta(target_heading, step)
        with self._lock:
            self._heading = target_heading
            self._lat = _clamp_lat(lat + dlat)
            self._lng = _clamp_lng(lng + dlng)

    # ------------------------------------------------------------------
    # 心跳后台线程
    # ------------------------------------------------------------------

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            with self._lock:
                lat = self._lat
                lng = self._lng
                battery = self._battery
                paused = self._paused
                moving = self._moving
                nav = self._nav_target

            # 模拟位置更新
            if not paused:
                if nav is not None:
                    self._apply_navigation()
                elif moving is not None:
                    self._apply_movement(moving)

            # 读取更新后的坐标
            with self._lock:
                lat = self._lat
                lng = self._lng
                battery = max(0.0, self._battery - _BATTERY_DRAIN_PER_BEAT)
                self._battery = battery

            payload = {
                'device_id': self.device_id,
                'lat': round(lat, 6),
                'lng': round(lng, 6),
                'status': 'PAUSED' if paused else 'ONLINE',
                'battery': round(battery, 1),
            }

            try:
                resp, body = _post_json(self._heartbeat_url, payload, timeout=5)
                if body.get('ok'):
                    srv_cmd = body.get('command', 'IDLE')
                    srv_target = body.get('target') or {}
                    robot_id = body.get('robot_id')
                    with self._lock:
                        self._server_cmd = srv_cmd
                        if robot_id is not None:
                            self._db_id = robot_id
                    self._handle_server_command(srv_cmd, srv_target)
                elif resp.status_code == 403:
                    _warn('设备被服务器拒绝（403），尝试重新注册')
                    self._ensure_registered()
                else:
                    _warn(f'心跳异常响应: {body}')
            except requests.exceptions.RequestException as e:
                _warn(f'心跳请求失败: {e}')

            if battery <= 0:
                _info('电量耗尽，模拟器自动停止')
                self._stop_event.set()
                break

            with self._lock:
                interval = self.interval
            self._stop_event.wait(timeout=interval)

    # ------------------------------------------------------------------
    # 处理服务器下发指令
    # ------------------------------------------------------------------

    def _handle_server_command(self, command, target):
        if command in ('IDLE', None):
            return

        if command == 'NAVIGATE':
            tlat = target.get('lat')
            tlng = target.get('lng')
            if tlat is not None and tlng is not None:
                with self._lock:
                    current_lat = self._lat
                    current_lng = self._lng
                    current_nav = self._nav_target
                dist = math.sqrt((float(tlat) - current_lat) ** 2 + (float(tlng) - current_lng) ** 2)
                if dist <= _NAV_ARRIVE_THRESHOLD and current_nav is None:
                    return
                with self._lock:
                    self._paused = False
                    self._nav_target = (float(tlat), float(tlng))
                    self._moving = 'NAVIGATE'
                _info(f'服务器导航指令 → 目标 ({tlat:.6f}, {tlng:.6f})')
            return

        if command in ('PICK_TRASH', 'DOCK'):
            _info(f'服务器指令: {command} — 已模拟')
            return

        if command in CONTROL_COMMANDS:
            self._apply_local_command(command)
            _info(f'服务器指令: {command} — 已执行')
            return

        _info(f'服务器指令: {command}（已收到）')

    # ------------------------------------------------------------------
    # 向服务器发送控制命令 / 导航
    # ------------------------------------------------------------------

    def _robot_id_payload(self):
        payload = {'device_id': self.device_id}
        with self._lock:
            db_id = self._db_id
        if db_id is not None:
            payload['id'] = db_id
        return payload

    def send_control(self, command):
        """通过 /api/robot/control 向服务器下发命令。"""
        payload = {**self._robot_id_payload(), 'command': command}
        try:
            resp, body = _post_json(self._control_url, payload, timeout=5)
            if body.get('ok'):
                _info(f'✔ 控制命令已下发: {command}')
                # 在本地也立即更新运动状态
                self._apply_local_command(command)
            else:
                _warn(f'控制命令失败: {body}')
        except requests.exceptions.RequestException as e:
            _warn(f'控制命令请求失败: {e}')

    def send_navigate(self, tlat, tlng):
        """通过 /api/robot/navigate 向服务器下发导航目标。"""
        payload = {**self._robot_id_payload(), 'lat': tlat, 'lng': tlng}
        try:
            resp, body = _post_json(self._navigate_url, payload, timeout=5)
            if body.get('ok'):
                with self._lock:
                    self._paused = False
                    self._nav_target = (tlat, tlng)
                    self._moving = 'NAVIGATE'
                _info(f'✔ 导航目标已设定: ({tlat:.6f}, {tlng:.6f})')
            else:
                _warn(f'导航命令失败: {body}')
        except requests.exceptions.RequestException as e:
            _warn(f'导航命令请求失败: {e}')

    def _apply_local_command(self, command):
        """命令下发后立即更新本地运动状态。"""
        movement_modes = {
            'FORWARD', 'FAST_FORWARD', 'SLOW_FORWARD',
            'BACK', 'LEFT', 'RIGHT', 'SPIN_LEFT', 'SPIN_RIGHT',
        }
        with self._lock:
            if command == 'STOP' or command == 'HOLD_POSITION':
                self._moving = None
                self._nav_target = None
            elif command == 'CANCEL_NAVIGATION':
                self._nav_target = None
                self._moving = None
            elif command == 'PAUSE':
                self._paused = True
            elif command == 'RESUME':
                self._paused = False
            elif command in movement_modes:
                self._paused = False
                self._nav_target = None
                self._moving = command
            elif command == 'RESET':
                self._heading = 0.0
                self._paused = False
                self._moving = None
                self._nav_target = None
            elif command == 'RETURN_HOME':
                self._paused = False
                self._nav_target = (self._home_lat, self._home_lng)
                self._moving = 'NAVIGATE'

    # ------------------------------------------------------------------
    # 状态展示
    # ------------------------------------------------------------------

    def print_status(self):
        with self._lock:
            lat = self._lat
            lng = self._lng
            battery = self._battery
            heading = self._heading
            status = self._status
            moving = self._moving
            nav = self._nav_target
            paused = self._paused
            srv_cmd = self._server_cmd

        nav_str = f'→ ({nav[0]:.6f}, {nav[1]:.6f})' if nav else '无'
        move_str = moving or ('暂停' if paused else '静止')
        print(f"""
┌─────────────── 机器人状态 ───────────────┐
│ 设备 ID : {self.device_id:<34}│
│ 坐标    : lat={lat:.6f}  lng={lng:.6f}    │
│ 电量    : {battery:.1f}%                               │
│ 朝向    : {heading:.1f}° (0=北，顺时针)              │
│ 运动    : {move_str:<36}│
│ 导航目标: {nav_str:<36}│
│ 服务器令: {srv_cmd:<36}│
└──────────────────────────────────────────┘""")
        print('> ', end='', flush=True)


# ---------------------------------------------------------------------------
# 交互式命令行主循环
# ---------------------------------------------------------------------------

def _interactive_loop(sim: RobotSimulator):
    print(_HELP_TEXT)
    print('输入 help 查看指令列表，输入 quit 退出。\n')

    while not sim._stop_event.is_set():
        try:
            raw = input('> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        # ── 退出 ──
        if cmd in ('quit', 'q', 'exit'):
            print('正在退出...')
            break

        # ── 帮助 ──
        if cmd in ('help', '?'):
            print(_HELP_TEXT)
            continue

        # ── 状态显示 ──
        if cmd == 'status':
            sim.print_status()
            continue

        # ── 电量设置 ──
        if cmd == 'battery':
            if not args:
                print('用法: battery <0-100>')
                print('> ', end='', flush=True)
                continue
            try:
                val = max(0.0, min(100.0, float(args[0])))
                with sim._lock:
                    sim._battery = val
                _info(f'电量已设为 {val:.1f}%')
            except ValueError:
                print('无效的电量值')
                print('> ', end='', flush=True)
            continue

        # ── 朝向设置 ──
        if cmd == 'heading':
            if not args:
                print('用法: heading <0-359>')
                print('> ', end='', flush=True)
                continue
            try:
                val = float(args[0]) % 360
                with sim._lock:
                    sim._heading = val
                _info(f'朝向已设为 {val:.1f}°')
            except ValueError:
                print('无效的朝向值')
                print('> ', end='', flush=True)
            continue

        # ── 心跳间隔 ──
        if cmd == 'interval':
            if not args:
                print('用法: interval <秒>')
                print('> ', end='', flush=True)
                continue
            try:
                val = max(0.5, float(args[0]))
                with sim._lock:
                    sim.interval = val
                _info(f'心跳间隔已设为 {val:.1f}s')
            except ValueError:
                print('无效的间隔值')
                print('> ', end='', flush=True)
            continue

        # ── 导航 ──
        if cmd == 'nav':
            if len(args) < 2:
                print('用法: nav <lat> <lng>   例: nav 30.512 114.305')
                print('> ', end='', flush=True)
                continue
            try:
                tlat = float(args[0])
                tlng = float(args[1])
            except ValueError:
                print('坐标格式错误，请输入数字')
                print('> ', end='', flush=True)
                continue
            if not (-90 <= tlat <= 90) or not (-180 <= tlng <= 180):
                print('坐标超出有效范围')
                print('> ', end='', flush=True)
                continue
            sim.send_navigate(tlat, tlng)
            continue

        # ── 控制命令（别名 + 完整命令名）──
        server_cmd = _CMD_ALIAS.get(cmd) or (cmd.upper() if cmd.upper() in CONTROL_COMMANDS else None)
        if server_cmd:
            sim.send_control(server_cmd)
            continue

        print(f'未知命令: {cmd}  （输入 help 查看指令列表）')
        print('> ', end='', flush=True)

    sim.stop()




IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
TEXT_EXTENSIONS = {".txt", ".json", ".csv", ".yaml", ".yml", ".log"}
TABLE_COLUMNS = ["标签", "置信度(0-1)", "x1", "y1", "x2", "y2"]

CONTROL_COMMANDS = {
    "FORWARD", "BACK", "LEFT", "RIGHT", "STOP",
    "PICK_TRASH", "RESET", "PAUSE", "RESUME",
    "SLOW_FORWARD", "FAST_FORWARD", "SPIN_LEFT", "SPIN_RIGHT",
    "HOLD_POSITION", "CANCEL_NAVIGATION", "RETURN_HOME", "DOCK",
}

CMD_ALIASES = {
    "f": "FORWARD",
    "forward": "FORWARD",
    "b": "BACK",
    "back": "BACK",
    "backward": "BACK",
    "biede": "BACK",
    "bide": "BACK",
    "l": "LEFT",
    "left": "LEFT",
    "r": "RIGHT",
    "right": "RIGHT",
    "s": "STOP",
    "stop": "STOP",
    "pause": "PAUSE",
    "resume": "RESUME",
    "sf": "SLOW_FORWARD",
    "ff": "FAST_FORWARD",
}

if QT_BINDING is not None:
    QT_HORIZONTAL = getattr(Qt, "Horizontal", Qt.Orientation.Horizontal)
    QT_ALIGN_CENTER = getattr(Qt, "AlignCenter", Qt.AlignmentFlag.AlignCenter)
    QT_USER_ROLE = getattr(Qt, "UserRole", Qt.ItemDataRole.UserRole)
    QT_KEEP_ASPECT = getattr(Qt, "KeepAspectRatio", Qt.AspectRatioMode.KeepAspectRatio)
    QT_SMOOTH_TRANSFORM = getattr(
        Qt,
        "SmoothTransformation",
        Qt.TransformationMode.SmoothTransformation,
    )
    QHEADER_STRETCH = getattr(QHeaderView, "Stretch", QHeaderView.ResizeMode.Stretch)
else:
    QT_HORIZONTAL = None
    QT_ALIGN_CENTER = None
    QT_USER_ROLE = None
    QT_KEEP_ASPECT = None
    QT_SMOOTH_TRANSFORM = None
    QHEADER_STRETCH = None

MOVE_STEP_DEG = 0.00001
FAST_MULTIPLIER = 3.0
SLOW_MULTIPLIER = 0.4
NAV_STEP_RATIO = 0.08
NAV_ARRIVE_THRESHOLD = 0.00003
BATTERY_DRAIN_PER_BEAT = 0.03
ACTIVE_SYNC_MAX_INTERVAL_MS = 500


@dataclass
class ClusterRobotConfig:
    device_id: str
    name: str = "SimRobotQt"
    lat: float = 30.5
    lng: float = 114.3
    location: str = "模拟道路"


def _normalize_server_base(raw: str) -> str:
    base = (raw or "").strip()
    if not base:
        return ""
    if "://" not in base:
        base = f"http://{base}"
    return base.rstrip("/")


class SimRobotWorkbench(QMainWindow):  # type: ignore[misc]
    def __init__(self, server: str, device_id: str):
        super().__init__()
        self.setWindowTitle(f"TrashDet SimRobot Qt 智能控制台 ({QT_BINDING})")
        self.resize(1320, 820)

        self.current_folder: Optional[Path] = None
        self.current_file: Optional[Path] = None
        self.last_source_path: Optional[str] = None
        self.last_result_path: Optional[str] = None

        self.upload_cursor = 0

        self.robot_db_id: Optional[int] = None
        self.robot_battery = 92.0
        self.robot_heading = 0.0
        self.robot_paused = False
        self.robot_moving: Optional[str] = None
        self.robot_nav_target: Optional[tuple[float, float]] = None
        self.robot_nav_queue: List[tuple[float, float]] = []
        self.robot_last_arrived_target: Optional[tuple[float, float]] = None
        self.last_server_command = "IDLE"

        self.upload_timer = QTimer(self)
        self.upload_timer.timeout.connect(self._upload_next_image_once)

        self.robot_timer = QTimer(self)
        self.robot_timer.timeout.connect(self._robot_tick)

        self.cluster_windows: List[SimRobotWorkbench] = []

        self._build_ui(server=server, device_id=device_id)
        self._apply_styles()  # 必须在 _build_ui 之后，确保 image_preview 已初始化
        self._update_robot_dashboard()
        self.robot_sync_btn.click()

    # ----------------------------- UI -----------------------------

    def _build_ui(self, server: str, device_id: str):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        config_box = QGroupBox("连接参数 / 位置信息")
        cfg_grid = QGridLayout(config_box)


        self.server_edit = QLineEdit(server)
        self.server_edit.setPlaceholderText("后端地址，例如 http://127.0.0.1:5000")

        self.device_edit = QLineEdit(device_id)
        self.device_edit.setPlaceholderText("设备 ID")

        self.register_device_btn = QPushButton("注册设备")
        self.register_device_btn.clicked.connect(self._register_device_clicked)

        self.location_edit = QLineEdit("模拟道路")
        self.location_edit.setPlaceholderText("地点描述（可选）")

        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setDecimals(6)
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setValue(30.500000)

        self.lng_spin = QDoubleSpinBox()
        self.lng_spin.setDecimals(6)
        self.lng_spin.setRange(-180.0, 180.0)
        self.lng_spin.setValue(114.300000)


        cfg_grid.addWidget(QLabel("服务器"), 0, 0)
        cfg_grid.addWidget(self.server_edit, 0, 1)
        cfg_grid.addWidget(QLabel("设备 ID"), 0, 2)
        cfg_grid.addWidget(self.device_edit, 0, 3)
        cfg_grid.addWidget(self.register_device_btn, 0, 4)

        cfg_grid.addWidget(QLabel("纬度"), 1, 0)
        cfg_grid.addWidget(self.lat_spin, 1, 1)
        cfg_grid.addWidget(QLabel("经度"), 1, 2)
        cfg_grid.addWidget(self.lng_spin, 1, 3)

        cfg_grid.addWidget(QLabel("位置描述"), 2, 0)
        cfg_grid.addWidget(self.location_edit, 2, 1, 1, 3)

        root_layout.addWidget(config_box)

        cluster_box = QGroupBox("集群机器人模拟")
        cluster_layout = QVBoxLayout(cluster_box)

        cluster_tip = QLabel(
            "每行一个机器人：设备ID[,名称,纬度,经度,位置]\n"
            "示例：SIM_001,北区1号,30.500100,114.300100,北区主路"
        )
        cluster_layout.addWidget(cluster_tip)

        self.cluster_config_edit = QTextEdit()
        self.cluster_config_edit.setPlaceholderText(
            "SIM_001,北区1号,30.500100,114.300100,北区主路\n"
            "SIM_002,北区2号,30.500300,114.300200,北区支路"
        )
        self.cluster_config_edit.setMinimumHeight(95)
        cluster_layout.addWidget(self.cluster_config_edit)

        cluster_btn_row = QHBoxLayout()
        self.spawn_cluster_btn = QPushButton("创建集群控制台")
        self.spawn_cluster_btn.clicked.connect(self.spawn_cluster_workbenches)
        cluster_btn_row.addWidget(self.spawn_cluster_btn)
        cluster_btn_row.addStretch(1)
        cluster_layout.addLayout(cluster_btn_row)

        root_layout.addWidget(cluster_box)

        control_box = QGroupBox("上传节奏 / 机器人控制")
        ctl_grid = QGridLayout(control_box)

        self.upload_interval_spin = QDoubleSpinBox()
        self.upload_interval_spin.setDecimals(1)
        self.upload_interval_spin.setRange(0.5, 60.0)
        self.upload_interval_spin.setValue(2.0)
        self.upload_interval_spin.valueChanged.connect(self._on_upload_interval_changed)

        self.upload_next_btn = QPushButton("上传下一张")
        self.upload_next_btn.clicked.connect(self.upload_next_single)

        self.interval_upload_btn = QPushButton("开启间隔上传")
        self.interval_upload_btn.setCheckable(True)
        self.interval_upload_btn.clicked.connect(self.toggle_interval_upload)

        self.heartbeat_interval_spin = QDoubleSpinBox()
        self.heartbeat_interval_spin.setDecimals(1)
        self.heartbeat_interval_spin.setRange(0.5, 30.0)
        self.heartbeat_interval_spin.setValue(0.5)
        self.heartbeat_interval_spin.valueChanged.connect(self._on_heartbeat_interval_changed)


        self.robot_sync_btn = QPushButton("开启机器人同步")
        self.robot_sync_btn.setCheckable(True)
        self.robot_sync_btn.clicked.connect(self.toggle_robot_sync)
        # 启动时不自动注册，需手动点击注册按钮

        self.robot_pos_label = QLabel("位置: (30.500000, 114.300000)")
        self.robot_heading_label = QLabel("朝向: 0.0°")
        self.robot_mode_label = QLabel("动作: 静止")
        self.robot_battery_label = QLabel("电量: 92.0%")
        self.robot_server_cmd_label = QLabel("服务器指令: IDLE")

        self.move_speed_spin = QDoubleSpinBox()
        self.move_speed_spin.setDecimals(2)
        self.move_speed_spin.setRange(0.20, 8.00)
        self.move_speed_spin.setSingleStep(0.10)
        self.move_speed_spin.setValue(1.00)

        self.turn_speed_spin = QDoubleSpinBox()
        self.turn_speed_spin.setDecimals(1)
        self.turn_speed_spin.setRange(1.0, 45.0)
        self.turn_speed_spin.setSingleStep(1.0)
        self.turn_speed_spin.setValue(10.0)

        self.robot_speed_label = QLabel("速度倍率: 1.00x / 转向步进: 10.0°")

        self.forward_btn = QPushButton("前进")
        self.forward_btn.clicked.connect(lambda: self.send_robot_command("FORWARD"))
        self.back_btn = QPushButton("后退")
        self.back_btn.clicked.connect(lambda: self.send_robot_command("BACK"))
        self.left_btn = QPushButton("左转")
        self.left_btn.clicked.connect(lambda: self.send_robot_command("LEFT"))
        self.right_btn = QPushButton("右转")
        self.right_btn.clicked.connect(lambda: self.send_robot_command("RIGHT"))
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(lambda: self.send_robot_command("STOP"))

        self.custom_cmd_edit = QLineEdit()
        self.custom_cmd_edit.setPlaceholderText("输入自定义指令，例如 pick_trash、dock、biede")
        self.send_custom_cmd_btn = QPushButton("发送指令")
        self.send_custom_cmd_btn.clicked.connect(self.send_custom_robot_command)

        ctl_grid.addWidget(QLabel("上传间隔(秒)"), 0, 0)
        ctl_grid.addWidget(self.upload_interval_spin, 0, 1)
        ctl_grid.addWidget(self.upload_next_btn, 0, 2)
        ctl_grid.addWidget(self.interval_upload_btn, 0, 3)

        ctl_grid.addWidget(QLabel("心跳间隔(秒)"), 1, 0)
        ctl_grid.addWidget(self.heartbeat_interval_spin, 1, 1)
        ctl_grid.addWidget(self.robot_sync_btn, 1, 2, 1, 2)

        ctl_grid.addWidget(self.robot_pos_label, 2, 0, 1, 2)
        ctl_grid.addWidget(self.robot_heading_label, 2, 2, 1, 2)
        ctl_grid.addWidget(self.robot_mode_label, 3, 0, 1, 2)
        ctl_grid.addWidget(self.robot_battery_label, 3, 2, 1, 2)
        ctl_grid.addWidget(self.robot_server_cmd_label, 4, 0, 1, 4)

        ctl_grid.addWidget(QLabel("移动速度倍率"), 5, 0)
        ctl_grid.addWidget(self.move_speed_spin, 5, 1)
        ctl_grid.addWidget(QLabel("转向步进(°)"), 5, 2)
        ctl_grid.addWidget(self.turn_speed_spin, 5, 3)
        ctl_grid.addWidget(self.robot_speed_label, 6, 0, 1, 4)

        ctl_grid.addWidget(self.forward_btn, 7, 0)
        ctl_grid.addWidget(self.back_btn, 7, 1)
        ctl_grid.addWidget(self.left_btn, 7, 2)
        ctl_grid.addWidget(self.right_btn, 7, 3)
        ctl_grid.addWidget(self.stop_btn, 8, 0)
        ctl_grid.addWidget(self.custom_cmd_edit, 8, 1, 1, 2)
        ctl_grid.addWidget(self.send_custom_cmd_btn, 8, 3)

        root_layout.addWidget(control_box)

        splitter = QSplitter(QT_HORIZONTAL)
        root_layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("请选择本地模拟数据目录")

        self.pick_folder_btn = QPushButton("选择文件夹")
        self.pick_folder_btn.clicked.connect(self.select_folder)

        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.pick_folder_btn)

        left_layout.addLayout(folder_row)

        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        left_layout.addWidget(self.file_list, 1)

        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        preview_box = QGroupBox("文件预览")
        preview_layout = QVBoxLayout(preview_box)

        self.preview_title = QLabel("尚未选择文件")
        self.preview_title.setStyleSheet("font-weight: 700;")
        preview_layout.addWidget(self.preview_title)

        self.image_preview = QLabel("图片预览区域")
        self.image_preview.setAlignment(QT_ALIGN_CENTER)
        self.image_preview.setMinimumHeight(300)
        preview_layout.addWidget(self.image_preview)

        right_layout.addWidget(preview_box)

        action_row = QHBoxLayout()
        self.detect_btn = QPushButton("调用平台识别")
        self.detect_btn.clicked.connect(self.detect_current_file)

        self.batch_detect_btn = QPushButton("批量识别")
        self.batch_detect_btn.clicked.connect(self.batch_detect_files)

        self.upload_btn = QPushButton("上传润色结果")
        self.upload_btn.clicked.connect(self.upload_results)

        action_row.addWidget(self.detect_btn)
        action_row.addWidget(self.batch_detect_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.upload_btn)
        right_layout.addLayout(action_row)

        self.result_table = QTableWidget(0, len(TABLE_COLUMNS))
        self.result_table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.result_table.horizontalHeader().setSectionResizeMode(QHEADER_STRETCH)
        self.result_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.result_table, 1)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(110)
        right_layout.addWidget(self.log_view)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

        self._log("Qt 控制台已启动")

    def _parse_cluster_configs(self) -> List[ClusterRobotConfig]:
        lines = [line.strip() for line in self.cluster_config_edit.toPlainText().splitlines() if line.strip()]
        configs: List[ClusterRobotConfig] = []
        for index, line in enumerate(lines, start=1):
            parts = [part.strip() for part in line.split(',')]
            if not parts or not parts[0]:
                raise ValueError(f"第 {index} 行缺少设备ID")

            device_id = parts[0]
            name = parts[1] if len(parts) >= 2 and parts[1] else "SimRobotQt"

            lat = self.lat_spin.value()
            lng = self.lng_spin.value()
            if len(parts) >= 3 and parts[2]:
                lat = float(parts[2])
            if len(parts) >= 4 and parts[3]:
                lng = float(parts[3])
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                raise ValueError(f"第 {index} 行经纬度超出范围")

            location = parts[4] if len(parts) >= 5 and parts[4] else "模拟道路"
            configs.append(ClusterRobotConfig(device_id=device_id, name=name, lat=lat, lng=lng, location=location))
        return configs

    def spawn_cluster_workbenches(self):
        try:
            configs = self._parse_cluster_configs()
        except ValueError as error:
            self._warn(str(error))
            return

        if not configs:
            self._warn("请先填写至少一行机器人配置")
            return

        server = self.server_edit.text().strip()
        created = 0
        for cfg in configs:
            child = SimRobotWorkbench(server=server, device_id=cfg.device_id)
            child.device_edit.setText(cfg.device_id)
            child.location_edit.setText(cfg.location)
            child.lat_spin.setValue(cfg.lat)
            child.lng_spin.setValue(cfg.lng)
            child.setWindowTitle(f"TrashDet SimRobot Qt 智能控制台 ({QT_BINDING}) - {cfg.name} [{cfg.device_id}]")
            child.show()
            self.cluster_windows.append(child)
            created += 1

        self._log(f"已创建 {created} 个集群机器人控制台")

    def _register_device_clicked(self):
        base = self._api_base()
        device_id = self.device_edit.text().strip()
        if not base.startswith("http"):
            self._warn("服务器地址格式无效")
            return
        if not device_id:
            self._warn("请输入设备ID")
            return

        url = f"{base}/api/robot/register_device"
        payload = {"device_id": device_id, "name": "SimRobotQt"}

        try:
            resp = requests.post(url, json=payload, timeout=5)
            body = resp.json() if resp.content else {}
            if body.get("ok") or body.get("robot_id"):
                self._log(f"注册成功，robot_id={body.get('robot_id')}")
                robot_id_raw = body.get("robot_id")
                try:
                    self.robot_db_id = int(robot_id_raw) if robot_id_raw is not None else None
                except (TypeError, ValueError):
                    self.robot_db_id = None
            else:
                self._warn(f"注册失败: {body.get('msg') or '未知错误'}")
        except requests.RequestException as error:
            self._warn(f"注册请求失败: {error}")
        except ValueError as error:
            self._warn(f"注册响应解析失败: {error}")

    def closeEvent(self, event):
        for window in list(self.cluster_windows):
            try:
                window.close()
            except Exception:
                pass
        self.cluster_windows.clear()
        super().closeEvent(event)

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #f5f8ff, stop:1 #ecf8f2);
            }
            QGroupBox {
                border: 1px solid #d7dee8;
                border-radius: 10px;
                margin-top: 10px;
                padding: 12px 10px 10px 10px;
                background: rgba(255, 255, 255, 0.9);
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #1e3a5f;
            }
            QLineEdit, QDoubleSpinBox, QTextEdit, QListWidget, QTableWidget {
                border: 1px solid #cfd8e3;
                border-radius: 8px;
                background: #ffffff;
                padding: 4px;
            }
            QPushButton {
                border: 0;
                border-radius: 8px;
                padding: 7px 12px;
                color: #ffffff;
                background: #2274a5;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1d5f87;
            }
            QPushButton:checked {
                background: #1f9d74;
            }
            QLabel {
                color: #24364b;
            }
            """
        )
        self.image_preview.setStyleSheet("border: 1px solid #d1d9e8; background: #f6f9ff;")

    # -------------------------- Helpers ---------------------------

    def _api_base(self) -> str:
        return _normalize_server_base(self.server_edit.text())

    def _log(self, message: str):
        self.log_view.append(message)
        self.statusBar().showMessage(message)

    def _warn(self, text: str):
        QMessageBox.warning(self, "提示", text)

    def _error(self, text: str):
        QMessageBox.critical(self, "错误", text)

    def _is_image(self, path: Path) -> bool:
        return path.suffix.lower() in IMAGE_EXTENSIONS

    def _is_text_data(self, path: Path) -> bool:
        return path.suffix.lower() in TEXT_EXTENSIONS

    def _set_table_value(self, row: int, col: int, value: str):
        item = QTableWidgetItem(value)
        self.result_table.setItem(row, col, item)

    def _clamp_lat(self, value: float) -> float:
        return max(-90.0, min(90.0, value))

    def _clamp_lng(self, value: float) -> float:
        return max(-180.0, min(180.0, value))

    def _heading_to_delta(self, heading_deg: float, step: float) -> tuple[float, float]:
        rad = math.radians(heading_deg)
        dlat = math.cos(rad) * step
        dlng = math.sin(rad) * step
        return dlat, dlng

    def _normalize_command(self, raw: str) -> str:
        cleaned = (raw or "").strip()
        if not cleaned:
            return ""
        cmd = CMD_ALIASES.get(cleaned.lower(), cleaned.upper())
        return cmd

    def _normalize_nav_point(self, raw_point) -> Optional[tuple[float, float]]:
        if isinstance(raw_point, dict):
            lat_raw = raw_point.get("lat")
            lng_raw = raw_point.get("lng")
        elif isinstance(raw_point, (list, tuple)) and len(raw_point) >= 2:
            lat_raw = raw_point[0]
            lng_raw = raw_point[1]
        else:
            return None

        if lat_raw is None or lng_raw is None:
            return None

        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(lat) or not math.isfinite(lng):
            return None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            return None
        return (lat, lng)

    def _append_nav_points(self, raw_points, output: List[tuple[float, float]]):
        if raw_points is None:
            return

        point = self._normalize_nav_point(raw_points)
        if point is not None:
            output.append(point)
            return

        if isinstance(raw_points, (list, tuple)):
            for item in raw_points:
                nested_point = self._normalize_nav_point(item)
                if nested_point is not None:
                    output.append(nested_point)
                    continue
                if isinstance(item, dict):
                    for key in ("waypoints", "points", "path", "planned_path", "targets", "route"):
                        self._append_nav_points(item.get(key), output)
            return

        if isinstance(raw_points, dict):
            for key in ("waypoints", "points", "path", "planned_path", "targets", "route"):
                self._append_nav_points(raw_points.get(key), output)

    def _extract_nav_route(self, target, response_body) -> List[tuple[float, float]]:
        route_points: List[tuple[float, float]] = []

        if isinstance(target, dict):
            for key in ("waypoints", "points", "path", "planned_path", "targets", "route"):
                self._append_nav_points(target.get(key), route_points)
        elif isinstance(target, (list, tuple)):
            self._append_nav_points(target, route_points)

        if isinstance(response_body, dict):
            for key in (
                "waypoints",
                "points",
                "path",
                "planned_path",
                "targets",
                "target_list",
                "route",
                "patrol_path",
                "navigation_points",
            ):
                self._append_nav_points(response_body.get(key), route_points)

        normalized: List[tuple[float, float]] = []
        for point in route_points:
            if not normalized:
                normalized.append(point)
                continue
            prev = normalized[-1]
            if math.hypot(point[0] - prev[0], point[1] - prev[1]) > 1e-12:
                normalized.append(point)

        return normalized

    def _same_nav_point(self, p1: tuple[float, float], p2: tuple[float, float], tolerance: float = 1e-9) -> bool:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) <= tolerance

    def _find_route_point_index(self, route: List[tuple[float, float]], point: tuple[float, float]) -> int:
        for index, candidate in enumerate(route):
            if self._same_nav_point(candidate, point, tolerance=max(NAV_ARRIVE_THRESHOLD * 1.2, 1e-9)):
                return index
        return -1

    def _apply_route_navigation(self, route_points: List[tuple[float, float]]) -> bool:
        if not route_points:
            return False

        current_target = self.robot_nav_target
        if current_target is not None:
            matched_index = self._find_route_point_index(route_points, current_target)
            if matched_index > 0:
                route_points = route_points[matched_index:]

        current_pos = (self.lat_spin.value(), self.lng_spin.value())
        while route_points and math.hypot(route_points[0][0] - current_pos[0], route_points[0][1] - current_pos[1]) <= NAV_ARRIVE_THRESHOLD:
            route_points = route_points[1:]

        if not route_points:
            self.robot_nav_target = None
            self.robot_nav_queue = []
            self.robot_moving = None
            return False

        if self.robot_nav_target is not None and self.robot_nav_queue:
            current_route = [self.robot_nav_target, *self.robot_nav_queue]
            if len(current_route) == len(route_points):
                same_route = all(self._same_nav_point(a, b, tolerance=1e-9) for a, b in zip(current_route, route_points))
                if same_route:
                    self.robot_paused = False
                    self.robot_moving = "NAVIGATE"
                    return True

        self.robot_paused = False
        self.robot_last_arrived_target = None
        self.robot_nav_target = route_points[0]
        self.robot_nav_queue = route_points[1:]
        self.robot_moving = "NAVIGATE"
        self._log(f"收到航点队列，共 {len(route_points)} 点，当前前往 ({route_points[0][0]:.6f}, {route_points[0][1]:.6f})")
        return True

    # ----------------------- Folder / Preview ----------------------

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择模拟数据目录")
        if not folder:
            return

        self.current_folder = Path(folder)
        self.folder_edit.setText(folder)
        self.file_list.clear()
        self.upload_cursor = 0

        files = [p for p in self.current_folder.iterdir() if p.is_file()]
        files.sort(key=lambda p: p.name.lower())

        for path in files:
            item = QListWidgetItem(path.name)
            item.setData(QT_USER_ROLE, str(path))
            self.file_list.addItem(item)

        self._log(f"已加载目录: {folder}，共 {len(files)} 个文件")

    def on_file_selected(self):
        items = self.file_list.selectedItems()
        if not items:
            return

        file_path = Path(items[0].data(QT_USER_ROLE))
        self.current_file = file_path
        self.preview_title.setText(f"当前文件: {file_path.name}")

        if self._is_image(file_path):
            self._preview_local_image(file_path)
            return

        self.image_preview.setText("该文件不是图片，详细信息已输出到日志")
        self.image_preview.setPixmap(QPixmap())

        if self._is_text_data(file_path):
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                self._log(f"文本文件预览({file_path.name}): {content[:160].replace(chr(10), ' ')}")
            except OSError as error:
                self._log(f"读取失败: {error}")
        else:
            size_kb = file_path.stat().st_size / 1024.0
            self._log(
                f"文件信息: {file_path.name}, 大小 {size_kb:.2f} KB, 类型 {file_path.suffix or '无扩展名'}"
            )

    def _preview_local_image(self, path: Path):
        pix = QPixmap(str(path))
        if pix.isNull():
            self.image_preview.setText("图片加载失败")
            return

        scaled = pix.scaled(
            self.image_preview.width() if self.image_preview.width() > 10 else 760,
            self.image_preview.height() if self.image_preview.height() > 10 else 380,
            QT_KEEP_ASPECT,
            QT_SMOOTH_TRANSFORM,
        )
        self.image_preview.setPixmap(scaled)

    def _preview_remote_annotated(self, rel_path: str):
        url = f"{self._api_base()}/{rel_path.lstrip('/')}"
        try:
            resp = requests.get(url, timeout=12)
            resp.raise_for_status()
            pix = QPixmap()
            if not pix.loadFromData(resp.content):
                self._log("识别后图片预览失败（解码失败）")
                return
            scaled = pix.scaled(
                self.image_preview.width() if self.image_preview.width() > 10 else 760,
                self.image_preview.height() if self.image_preview.height() > 10 else 380,
                QT_KEEP_ASPECT,
                QT_SMOOTH_TRANSFORM,
            )
            self.image_preview.setPixmap(scaled)
            self._log(f"已预览识别后图片: {rel_path}")
        except requests.RequestException as error:
            self._log(f"识别后图片预览失败: {error}")

    # -------------------------- Detect ----------------------------

    def detect_current_file(self):
        if self.current_file is None:
            self._warn("请先选择文件")
            return

        if not self._is_image(self.current_file):
            self._warn("当前文件不是图片，无法调用 /api/detect")
            return

        result = self._detect_image_file(self.current_file, show_preview=True)
        if not result["ok"]:
            self._error(result["message"])
            return

        detections = result["detections"]
        self._fill_result_table(detections)

        self.last_source_path = result["source_path"]
        self.last_result_path = result["result_path"]

        self._log(f"识别完成: {self.current_file.name}，检测到 {len(detections)} 个目标")

    def _detect_image_file(self, image_path: Path, show_preview: bool = False) -> dict:
        base = self._api_base()
        if not base.startswith("http"):
            return {
                "ok": False,
                "message": "服务器地址格式无效",
                "detections": [],
                "source_path": None,
                "result_path": None,
            }

        url = f"{base}/api/detect"
        self._log(f"开始识别: {image_path.name}")

        try:
            with image_path.open("rb") as fp:
                files = {
                    "image": (image_path.name, fp, "application/octet-stream"),
                }
                data = {
                    "device_id": self.device_edit.text().strip(),
                    "latitude": f"{self.lat_spin.value():.6f}",
                    "longitude": f"{self.lng_spin.value():.6f}",
                    "source_type": "image",
                }
                resp = requests.post(url, files=files, data=data, timeout=60)

            payload = resp.json() if resp.content else {}
            if resp.status_code >= 400 or not payload.get("ok", False):
                msg = payload.get("message") or f"识别失败，HTTP {resp.status_code}"
                self._log(f"识别失败: {msg}")
                return {
                    "ok": False,
                    "message": msg,
                    "detections": [],
                    "source_path": None,
                    "result_path": None,
                }

            detections = payload.get("result") or []
            task = payload.get("task") or {}
            source_path = task.get("source_path") or f"simulator://{image_path.name}"
            result_path = payload.get("annotated_image_path")

            if show_preview and result_path:
                self._preview_remote_annotated(result_path)

            return {
                "ok": True,
                "message": "ok",
                "detections": detections,
                "source_path": source_path,
                "result_path": result_path,
            }

        except requests.RequestException as error:
            self._log(f"识别请求失败: {error}")
            return {
                "ok": False,
                "message": f"请求失败: {error}",
                "detections": [],
                "source_path": None,
                "result_path": None,
            }
        except ValueError as error:
            self._log(f"识别响应解析失败: {error}")
            return {
                "ok": False,
                "message": f"响应解析失败: {error}",
                "detections": [],
                "source_path": None,
                "result_path": None,
            }
        except OSError as error:
            self._log(f"文件读取失败: {error}")
            return {
                "ok": False,
                "message": f"文件读取失败: {error}",
                "detections": [],
                "source_path": None,
                "result_path": None,
            }

    def _list_image_files(self) -> List[Path]:
        images: List[Path] = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = Path(item.data(QT_USER_ROLE))
            if self._is_image(path):
                images.append(path)
        return images

    def batch_detect_files(self):
        image_files = self._list_image_files()
        if not image_files:
            self._warn("当前目录没有可识别的图片文件")
            return

        if not self._api_base().startswith("http"):
            self._warn("服务器地址格式无效")
            return

        self._log(f"批量识别开始，共 {len(image_files)} 张图片")
        ok_count = 0
        fail_count = 0
        failed_names: List[str] = []

        for idx, image_path in enumerate(image_files, start=1):
            self.statusBar().showMessage(f"批量识别中 {idx}/{len(image_files)}: {image_path.name}")
            QApplication.processEvents()

            result = self._detect_image_file(image_path, show_preview=False)
            if not result["ok"]:
                fail_count += 1
                failed_names.append(image_path.name)
                continue

            ok_count += 1
            self.current_file = image_path
            self.last_source_path = result["source_path"]
            self.last_result_path = result["result_path"]
            self._fill_result_table(result["detections"])

        if self.last_result_path:
            self._preview_remote_annotated(self.last_result_path)

        self._log(f"批量识别完成: 成功 {ok_count}，失败 {fail_count}")
        if failed_names:
            fail_text = "\n".join(failed_names[:8])
            QMessageBox.warning(
                self,
                "批量识别完成",
                f"成功 {ok_count}，失败 {fail_count}\n失败文件(最多8个):\n{fail_text}",
            )
        else:
            QMessageBox.information(self, "批量识别完成", f"全部完成，共 {ok_count} 张")

    def _to_upload_detections(self, detections: List[dict]) -> List[dict]:
        normalized: List[dict] = []
        for det in detections:
            label = str(det.get("label") or det.get("class_name") or "Unknown")
            conf = self._normalize_confidence(det.get("confidence"))
            bbox = det.get("bbox") or [0, 0, 0, 0]
            if not isinstance(bbox, list) or len(bbox) != 4:
                bbox = [0, 0, 0, 0]
            normalized.append({
                "label": label,
                "confidence": conf,
                "bbox": [
                    int(float(bbox[0])),
                    int(float(bbox[1])),
                    int(float(bbox[2])),
                    int(float(bbox[3])),
                ],
            })
        return normalized

    def _post_ingest_payload(self, payload: dict) -> dict:
        base = self._api_base()
        url = f"{base}/api/detect/ingest"

        try:
            resp = requests.post(url, json=payload, timeout=30)
            body = resp.json() if resp.content else {}
            if resp.status_code >= 400 or not body.get("ok", False):
                msg = body.get("message") or f"上传失败，HTTP {resp.status_code}"
                return {"ok": False, "message": msg, "body": body}
            return {"ok": True, "message": "ok", "body": body}
        except requests.RequestException as error:
            return {"ok": False, "message": f"上传请求失败: {error}", "body": {}}
        except ValueError as error:
            return {"ok": False, "message": f"上传响应解析失败: {error}", "body": {}}

    def _build_upload_payload(self, image_path: Path, source_path: str, result_path: Optional[str], detections: List[dict]) -> dict:
        return {
            "source_type": "simulator",
            "device_id": self.device_edit.text().strip() or None,
            "latitude": self.lat_spin.value(),
            "longitude": self.lng_spin.value(),
            "location": self.location_edit.text().strip() or "模拟道路",
            "source_path": source_path or f"simulator://{image_path.name}",
            "result_path": result_path,
            "detections": detections,
            "frame_index": 0,
        }

    def batch_detect_and_upload(self):
        image_files = self._list_image_files()
        if not image_files:
            self._warn("当前目录没有可识别的图片文件")
            return

        if not self._api_base().startswith("http"):
            self._warn("服务器地址格式无效")
            return

        self._log(f"批量识别并上传开始，共 {len(image_files)} 张图片")
        detect_ok = 0
        upload_ok = 0
        fail_count = 0

        for idx, image_path in enumerate(image_files, start=1):
            self.statusBar().showMessage(f"批量识别并上传中 {idx}/{len(image_files)}: {image_path.name}")
            QApplication.processEvents()

            detect_result = self._detect_image_file(image_path, show_preview=False)
            if not detect_result["ok"]:
                fail_count += 1
                continue

            detect_ok += 1
            detections = self._to_upload_detections(detect_result["detections"])
            payload = self._build_upload_payload(
                image_path,
                detect_result["source_path"] or f"simulator://{image_path.name}",
                detect_result["result_path"],
                detections,
            )

            upload_result = self._post_ingest_payload(payload)
            if not upload_result["ok"]:
                fail_count += 1
                self._log(f"上传失败({image_path.name}): {upload_result['message']}")
                continue

            upload_ok += 1
            self.current_file = image_path
            self.last_source_path = payload["source_path"]
            self.last_result_path = payload["result_path"]
            self._fill_result_table(detect_result["detections"])

        if self.last_result_path:
            self._preview_remote_annotated(self.last_result_path)

        self._log(
            f"批量识别并上传完成: 识别成功 {detect_ok}/{len(image_files)}，上传成功 {upload_ok}/{len(image_files)}，失败 {fail_count}"
        )
        QMessageBox.information(
            self,
            "批量任务完成",
            (
                f"总数: {len(image_files)}\n"
                f"识别成功: {detect_ok}\n"
                f"上传成功: {upload_ok}\n"
                f"失败: {fail_count}"
            ),
        )

    # -------------------- Interval / Single Upload --------------------

    def _on_upload_interval_changed(self):
        if self.upload_timer.isActive():
            ms = int(self.upload_interval_spin.value() * 1000)
            self.upload_timer.setInterval(ms)

    def toggle_interval_upload(self):
        if self.interval_upload_btn.isChecked():
            image_files = self._list_image_files()
            if not image_files:
                self._warn("当前目录没有可上传图片")
                self.interval_upload_btn.setChecked(False)
                return
            if self.upload_cursor >= len(image_files):
                self.upload_cursor = 0

            ms = int(self.upload_interval_spin.value() * 1000)
            self.upload_timer.start(ms)
            self.interval_upload_btn.setText("停止间隔上传")
            self._log(f"间隔上传已开启，间隔 {self.upload_interval_spin.value():.1f} 秒")
        else:
            self.upload_timer.stop()
            self.interval_upload_btn.setText("开启间隔上传")
            self._log("间隔上传已停止")

    def upload_next_single(self):
        self._upload_next_image_once()

    def _upload_next_image_once(self):
        image_files = self._list_image_files()
        if not image_files:
            if self.upload_timer.isActive():
                self.upload_timer.stop()
            self.interval_upload_btn.setChecked(False)
            self.interval_upload_btn.setText("开启间隔上传")
            self._warn("当前目录没有可上传图片")
            return

        if self.upload_cursor >= len(image_files):
            self.upload_cursor = 0
            if self.upload_timer.isActive():
                self.upload_timer.stop()
                self.interval_upload_btn.setChecked(False)
                self.interval_upload_btn.setText("开启间隔上传")
                self._log("间隔上传已完成一轮")
            return

        image_path = image_files[self.upload_cursor]
        self.upload_cursor += 1

        detect_result = self._detect_image_file(image_path, show_preview=False)
        if not detect_result["ok"]:
            self._log(f"单张流程失败({image_path.name}): {detect_result['message']}")
            return

        detections = self._to_upload_detections(detect_result["detections"])
        payload = self._build_upload_payload(
            image_path,
            detect_result["source_path"] or f"simulator://{image_path.name}",
            detect_result["result_path"],
            detections,
        )

        upload_result = self._post_ingest_payload(payload)
        if not upload_result["ok"]:
            self._log(f"单张上传失败({image_path.name}): {upload_result['message']}")
            return

        self.current_file = image_path
        self.last_source_path = payload["source_path"]
        self.last_result_path = payload["result_path"]
        self._fill_result_table(detect_result["detections"])

        if self.last_result_path:
            self._preview_remote_annotated(self.last_result_path)

        body = upload_result["body"]
        self._log(
            f"单张上传成功: {image_path.name}, task_id={body.get('task_id')}, inserted={body.get('inserted_items')}"
        )

    # ---------------------- Robot Simulation ----------------------

    def _on_heartbeat_interval_changed(self):
        self._refresh_robot_timer_interval()

    def _is_robot_actively_moving(self) -> bool:
        return bool((self.robot_nav_target is not None or self.robot_moving is not None) and not self.robot_paused)

    def _effective_heartbeat_interval_ms(self) -> int:
        base_ms = max(100, int(self.heartbeat_interval_spin.value() * 1000))
        if self._is_robot_actively_moving():
            # Keep movement/status updates responsive even if user sets a very large heartbeat interval.
            return min(base_ms, ACTIVE_SYNC_MAX_INTERVAL_MS)
        return base_ms

    def _refresh_robot_timer_interval(self):
        if self.robot_timer.isActive():
            self.robot_timer.setInterval(self._effective_heartbeat_interval_ms())

    def toggle_robot_sync(self):
        if self.robot_sync_btn.isChecked():
            self.robot_sync_btn.setText("停止机器人同步")
            self.robot_timer.start(self._effective_heartbeat_interval_ms())
            self._ensure_robot_registered()
            self._robot_tick()
            self._log("机器人同步已开启，位置将持续变化并上报")
        else:
            self.robot_sync_btn.setText("开启机器人同步")
            self.robot_timer.stop()
            self._log("机器人同步已停止")

    def _robot_tick(self):
        executed_immediately = self._sync_robot_heartbeat()
        if not executed_immediately:
            reached_nav_target = self._apply_robot_motion()
            if reached_nav_target:
                # Report arrival immediately so backend can switch task state/next command without extra delay.
                self._sync_robot_heartbeat()
        self._refresh_robot_timer_interval()
        self._update_robot_dashboard()

    def _apply_robot_motion(self):
        lat = self.lat_spin.value()
        lng = self.lng_spin.value()
        reached_nav_target = False

        if not self.robot_paused:
            if self.robot_nav_target is not None:
                tlat, tlng = self.robot_nav_target
                dist = math.sqrt((tlat - lat) ** 2 + (tlng - lng) ** 2)
                if dist <= NAV_ARRIVE_THRESHOLD:
                    if self.robot_nav_queue:
                        next_lat, next_lng = self.robot_nav_queue.pop(0)
                        self.robot_nav_target = (next_lat, next_lng)
                        self.robot_moving = "NAVIGATE"
                        self.robot_last_arrived_target = (tlat, tlng)
                        self._log(
                            f"已到达航点 ({tlat:.6f}, {tlng:.6f})，自动前往下一点 ({next_lat:.6f}, {next_lng:.6f})"
                        )
                    else:
                        self.robot_nav_target = None
                        self.robot_moving = None
                        self.robot_last_arrived_target = (tlat, tlng)
                        self._log(f"已到达目标 ({tlat:.6f}, {tlng:.6f})")
                    reached_nav_target = True
                else:
                    target_heading = math.degrees(math.atan2(tlng - lng, tlat - lat)) % 360
                    self.robot_heading = target_heading
                    step = min(dist * NAV_STEP_RATIO, MOVE_STEP_DEG * self.move_speed_spin.value() * FAST_MULTIPLIER)
                    dlat, dlng = self._heading_to_delta(target_heading, step)
                    lat += dlat
                    lng += dlng
            elif self.robot_moving:
                mode = self.robot_moving
                move_step = MOVE_STEP_DEG * self.move_speed_spin.value()
                turn_step = self.turn_speed_spin.value()
                if mode == "FORWARD":
                    step = move_step
                    dlat, dlng = self._heading_to_delta(self.robot_heading, step)
                    lat += dlat
                    lng += dlng
                elif mode == "BACK":
                    step = -move_step
                    dlat, dlng = self._heading_to_delta(self.robot_heading, step)
                    lat += dlat
                    lng += dlng
                elif mode == "SLOW_FORWARD":
                    step = move_step * SLOW_MULTIPLIER
                    dlat, dlng = self._heading_to_delta(self.robot_heading, step)
                    lat += dlat
                    lng += dlng
                elif mode == "FAST_FORWARD":
                    step = move_step * FAST_MULTIPLIER
                    dlat, dlng = self._heading_to_delta(self.robot_heading, step)
                    lat += dlat
                    lng += dlng
                elif mode == "LEFT":
                    self.robot_heading = (self.robot_heading - turn_step) % 360
                    # Differential-drive style turning: rotate while drifting slightly forward.
                    step = move_step * 0.30
                    dlat, dlng = self._heading_to_delta(self.robot_heading, step)
                    lat += dlat
                    lng += dlng
                elif mode == "RIGHT":
                    self.robot_heading = (self.robot_heading + turn_step) % 360
                    # Keep RIGHT behavior symmetrical with LEFT for smoother manual control.
                    step = move_step * 0.30
                    dlat, dlng = self._heading_to_delta(self.robot_heading, step)
                    lat += dlat
                    lng += dlng
                elif mode == "SPIN_LEFT":
                    self.robot_heading = (self.robot_heading - turn_step * 1.8) % 360
                elif mode == "SPIN_RIGHT":
                    self.robot_heading = (self.robot_heading + turn_step * 1.8) % 360

        lat = self._clamp_lat(lat)
        lng = self._clamp_lng(lng)
        self.lat_spin.setValue(lat)
        self.lng_spin.setValue(lng)
        self.robot_battery = max(0.0, self.robot_battery - BATTERY_DRAIN_PER_BEAT)
        return reached_nav_target

    def _ensure_robot_registered(self):
        base = self._api_base()
        if not base.startswith("http"):
            return

        heartbeat = self._post_robot_heartbeat()
        if heartbeat.get("ok"):
            body = heartbeat.get("body") or {}
            robot_id = body.get("robot_id")
            if robot_id is not None:
                try:
                    self.robot_db_id = int(robot_id)
                except (TypeError, ValueError):
                    pass
            command = body.get("command") or "IDLE"
            target = body.get("target") or {}
            self.last_server_command = str(command)
            self._handle_server_command(command, target, response_body=body)
            if command != "IDLE":
                self._apply_robot_motion()
                self._update_robot_dashboard()
            return

        if heartbeat.get("status") == 403:
            url = f"{base}/api/robot/register_device"
            payload = {
                "device_id": self.device_edit.text().strip(),
                "name": "SimRobotQt",
            }
            try:
                resp = requests.post(url, json=payload, timeout=5)
                body = resp.json() if resp.content else {}
                if body.get("ok"):
                    robot_id = body.get("robot_id")
                    if robot_id is not None:
                        self.robot_db_id = int(robot_id)
                    self._log("机器人已自动注册")
                    self._refresh_robot_id()
                else:
                    self._log(f"机器人注册失败: {body}")
            except requests.RequestException as error:
                self._log(f"机器人注册请求失败: {error}")
            except ValueError as error:
                self._log(f"机器人注册响应解析失败: {error}")

    def _post_robot_heartbeat(self) -> dict:
        base = self._api_base()
        url = f"{base}/api/robot/heartbeat"
        payload = {
            "device_id": self.device_edit.text().strip(),
            "lat": round(self.lat_spin.value(), 6),
            "lng": round(self.lng_spin.value(), 6),
            "status": "PAUSED" if self.robot_paused else "ONLINE",
            "battery": round(self.robot_battery, 1),
        }
        try:
            resp = requests.post(url, json=payload, timeout=5)
            body = resp.json() if resp.content else {}
            return {
                "ok": bool(body.get("ok")),
                "status": resp.status_code,
                "body": body,
            }
        except requests.RequestException as error:
            self._log(f"心跳请求失败: {error}")
            return {"ok": False, "status": None, "body": {}}
        except ValueError as error:
            self._log(f"心跳响应解析失败: {error}")
            return {"ok": False, "status": None, "body": {}}

    def _sync_robot_heartbeat(self) -> bool:
        result = self._post_robot_heartbeat()
        if not result["ok"]:
            if result["status"] == 403:
                self._ensure_robot_registered()
            return False

        body = result["body"]
        robot_id = body.get("robot_id")
        if robot_id is not None:
            try:
                self.robot_db_id = int(robot_id)
            except (TypeError, ValueError):
                pass
        command = body.get("command") or "IDLE"
        target = body.get("target") or {}
        self.last_server_command = str(command)
        self._handle_server_command(command, target, response_body=body)
        if command != "IDLE":
            # Execute immediately in the same heartbeat cycle.
            self._apply_robot_motion()
            return True
        return False

    def _handle_server_command(self, command: str, target: dict, response_body: Optional[dict] = None):
        if command in (None, "", "IDLE"):
            return
        if command == "NAVIGATE":
            route_points = self._extract_nav_route(target, response_body)
            if route_points and self._apply_route_navigation(route_points):
                return

            # 回退到单点导航
            tlat = target.get("lat")
            tlng = target.get("lng")
            if tlat is not None and tlng is not None:
                nav_lat = float(tlat)
                nav_lng = float(tlng)
                next_point = (nav_lat, nav_lng)

                # 如果当前目标和服务端目标一致，仅确保继续导航，不打断队列
                if self.robot_nav_target is not None and self._same_nav_point(
                    self.robot_nav_target,
                    next_point,
                    tolerance=max(NAV_ARRIVE_THRESHOLD * 0.5, 1e-9),
                ):
                    self.robot_moving = "NAVIGATE"
                    self.robot_paused = False
                    return

                # 单点导航时才替换当前目标并清空队列
                self.robot_nav_queue = []
                self.robot_nav_target = next_point
                self.robot_moving = "NAVIGATE"
                self.robot_paused = False
            return
        self._apply_local_command(str(command))

    def _apply_local_command(self, command: str):
        cmd = self._normalize_command(command)
        if not cmd:
            return

        if cmd in {"STOP", "HOLD_POSITION"}:
            self.robot_moving = None
            self.robot_nav_target = None
            self.robot_nav_queue = []
            self.robot_last_arrived_target = None
        elif cmd in {"FORWARD", "BACK", "SLOW_FORWARD", "FAST_FORWARD", "LEFT", "RIGHT", "SPIN_LEFT", "SPIN_RIGHT"}:
            self.robot_paused = False
            self.robot_nav_target = None
            self.robot_nav_queue = []
            self.robot_last_arrived_target = None
            self.robot_moving = cmd
        elif cmd == "PAUSE":
            self.robot_paused = True
        elif cmd == "RESUME":
            self.robot_paused = False
        elif cmd == "CANCEL_NAVIGATION":
            self.robot_nav_target = None
            self.robot_nav_queue = []
            self.robot_last_arrived_target = None
            self.robot_moving = None
        elif cmd == "RESET":
            self.robot_heading = 0.0
            self.robot_moving = None
            self.robot_nav_target = None
            self.robot_nav_queue = []
            self.robot_last_arrived_target = None
            self.robot_paused = False
        elif cmd == "RETURN_HOME":
            self.robot_paused = False
            self.robot_nav_target = (30.500000, 114.300000)
            self.robot_nav_queue = []
            self.robot_last_arrived_target = None
            self.robot_moving = "NAVIGATE"
        elif cmd in {"PICK_TRASH", "DOCK"}:
            pass

    def _apply_immediate_motion_feedback(self, command: str):
        move_commands = {
            "FORWARD",
            "BACK",
            "SLOW_FORWARD",
            "FAST_FORWARD",
            "LEFT",
            "RIGHT",
            "SPIN_LEFT",
            "SPIN_RIGHT",
            "RETURN_HOME",
        }
        if command in move_commands:
            self._apply_robot_motion()
            return
        if command == "RESUME" and (self.robot_moving or self.robot_nav_target is not None):
            self._apply_robot_motion()

    def _refresh_robot_id(self):
        base = self._api_base()
        url = f"{base}/api/robot/list"
        try:
            resp = requests.get(url, timeout=5)
            body = resp.json() if resp.content else {}
            if not body.get("ok"):
                return
            device_id = self.device_edit.text().strip()
            for robot in body.get("robots", []):
                if robot.get("device_id") == device_id:
                    robot_id = robot.get("id")
                    self.robot_db_id = int(robot_id) if robot_id is not None else None
                    return
        except (requests.RequestException, ValueError, TypeError):
            return

    def _post_control_command(self, command: str) -> tuple[bool, str]:
        base = self._api_base()
        if not base.startswith("http"):
            return False, "服务器地址格式无效"

        url = f"{base}/api/robot/control"
        payload = {
            "command": command,
            "device_id": self.device_edit.text().strip(),
        }
        if self.robot_db_id is not None:
            payload["id"] = self.robot_db_id

        try:
            resp = requests.post(url, json=payload, timeout=5)
            body = resp.json() if resp.content else {}
            if resp.status_code >= 400 or not body.get("ok", False):
                return False, body.get("msg") or body.get("message") or f"HTTP {resp.status_code}"
            return True, "ok"
        except requests.RequestException as error:
            return False, f"控制请求失败: {error}"
        except ValueError as error:
            return False, f"控制响应解析失败: {error}"

    def send_robot_command(self, command: str):
        cmd = self._normalize_command(command)
        if not cmd:
            self._warn("控制指令不能为空")
            return

        self._apply_local_command(cmd)
        self._apply_immediate_motion_feedback(cmd)
        ok, message = self._post_control_command(cmd)
        if ok:
            self._log(f"控制指令已发送: {cmd}")
        else:
            self._log(f"控制指令发送失败({cmd}): {message}，已本地执行模拟")

        if not self.robot_timer.isActive() and cmd in {
            "FORWARD", "BACK", "LEFT", "RIGHT", "SLOW_FORWARD", "FAST_FORWARD", "SPIN_LEFT", "SPIN_RIGHT"
        }:
            self._log("提示: 机器人同步未开启，方向键每次仅移动一步；开启机器人同步可持续移动")

        self._update_robot_dashboard()

    def send_custom_robot_command(self):
        raw = self.custom_cmd_edit.text().strip()
        if not raw:
            self._warn("请输入指令")
            return

        cmd = self._normalize_command(raw)
        self.send_robot_command(cmd)

    def _update_robot_dashboard(self):
        self.robot_pos_label.setText(f"位置: ({self.lat_spin.value():.6f}, {self.lng_spin.value():.6f})")
        self.robot_heading_label.setText(f"朝向: {self.robot_heading:.1f}°")
        mode_text = self.robot_moving or ("暂停" if self.robot_paused else "静止")
        self.robot_mode_label.setText(f"动作: {mode_text}")
        self.robot_battery_label.setText(f"电量: {self.robot_battery:.1f}%")
        self.robot_server_cmd_label.setText(f"服务器指令: {self.last_server_command}")
        self.robot_speed_label.setText(
            f"速度倍率: {self.move_speed_spin.value():.2f}x / 转向步进: {self.turn_speed_spin.value():.1f}°"
        )

    # ------------------------ Edit / Upload -----------------------

    def add_result_row(self):
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
        self._set_table_value(row, 0, "Unknown")
        self._set_table_value(row, 1, "0.5000")
        self._set_table_value(row, 2, "0")
        self._set_table_value(row, 3, "0")
        self._set_table_value(row, 4, "10")
        self._set_table_value(row, 5, "10")

    def delete_selected_rows(self):
        selected_rows = sorted({item.row() for item in self.result_table.selectedItems()}, reverse=True)
        for row in selected_rows:
            self.result_table.removeRow(row)

    def _normalize_confidence(self, raw) -> float:
        if raw is None:
            return 0.0
        if isinstance(raw, (int, float)):
            value = float(raw)
            if value > 1.0:
                value = value / 100.0
            return max(0.0, min(1.0, value))

        text = str(raw).strip().replace("%", "")
        if not text:
            return 0.0
        value = float(text)
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _fill_result_table(self, detections: List[dict]):
        self.result_table.setRowCount(0)

        for det in detections:
            row = self.result_table.rowCount()
            self.result_table.insertRow(row)

            label = str(det.get("class_name") or det.get("label") or "Unknown")
            conf = self._normalize_confidence(det.get("confidence"))

            bbox = det.get("bbox") or [0, 0, 0, 0]
            if not isinstance(bbox, list) or len(bbox) != 4:
                bbox = [0, 0, 0, 0]

            self._set_table_value(row, 0, label)
            self._set_table_value(row, 1, f"{conf:.4f}")
            self._set_table_value(row, 2, str(int(float(bbox[0]))))
            self._set_table_value(row, 3, str(int(float(bbox[1]))))
            self._set_table_value(row, 4, str(int(float(bbox[2]))))
            self._set_table_value(row, 5, str(int(float(bbox[3]))))

    def _collect_table_detections(self) -> List[dict]:
        detections: List[dict] = []

        for row in range(self.result_table.rowCount()):
            label_item = self.result_table.item(row, 0)
            conf_item = self.result_table.item(row, 1)
            x1_item = self.result_table.item(row, 2)
            y1_item = self.result_table.item(row, 3)
            x2_item = self.result_table.item(row, 4)
            y2_item = self.result_table.item(row, 5)

            label = (label_item.text().strip() if label_item else "")
            if not label:
                continue

            try:
                confidence = self._normalize_confidence(conf_item.text() if conf_item else "0")
                x1 = int(float(x1_item.text() if x1_item else "0"))
                y1 = int(float(y1_item.text() if y1_item else "0"))
                x2 = int(float(x2_item.text() if x2_item else "0"))
                y2 = int(float(y2_item.text() if y2_item else "0"))
            except ValueError:
                raise ValueError(f"第 {row + 1} 行存在非法数字，请检查置信度或坐标")

            detections.append({
                "label": label,
                "confidence": confidence,
                "bbox": [x1, y1, x2, y2],
            })

        return detections

    def upload_results(self):
        base = self._api_base()
        if not base.startswith("http"):
            self._warn("服务器地址格式无效")
            return

        try:
            detections = self._collect_table_detections()
        except ValueError as error:
            self._warn(str(error))
            return

        if not detections:
            self._warn("没有可上传的识别结果")
            return

        source_path = self.last_source_path
        if not source_path:
            if self.current_file:
                source_path = f"simulator://{self.current_file.name}"
            else:
                source_path = f"simulator://manual_{self.device_edit.text().strip() or 'device'}"

        payload = {
            "source_type": "simulator",
            "device_id": self.device_edit.text().strip() or None,
            "latitude": self.lat_spin.value(),
            "longitude": self.lng_spin.value(),
            "location": self.location_edit.text().strip() or "模拟道路",
            "source_path": source_path,
            "result_path": self.last_result_path,
            "detections": detections,
            "frame_index": 0,
        }

        self._log(f"开始上传人工润色结果，共 {len(detections)} 项")
        result = self._post_ingest_payload(payload)
        if not result["ok"]:
            self._error(result["message"])
            self._log(f"上传失败: {result['message']}")
            return

        body = result["body"]
        task_id = body.get("task_id")
        inserted = body.get("inserted_items")
        skipped = body.get("skipped_items")
        self._log(f"上传成功: task_id={task_id}, inserted={inserted}, skipped={skipped}")
        QMessageBox.information(self, "成功", f"上传完成\n任务ID: {task_id}\n入库条目: {inserted}")


def run_cli(argv=None):
    parser = argparse.ArgumentParser(
        description='TrashDet 机器人交互式终端模拟器',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--server',   default='http://127.0.0.1:5000', help='服务器地址')
    parser.add_argument('--id',       default='SIM_ROBOT_001',         help='设备 ID')
    parser.add_argument('--name',     default='Simulator',             help='设备名称')
    parser.add_argument('--lat',      type=float, default=30.5,        help='初始纬度')
    parser.add_argument('--lng',      type=float, default=114.3,       help='初始经度')
    parser.add_argument('--battery',  type=float, default=90.0,        help='初始电量 (0-100)')
    parser.add_argument('--interval', type=float, default=0.5,         help='心跳间隔（秒）')
    args = parser.parse_args(argv)

    sim = RobotSimulator(
        server=args.server,
        device_id=args.id,
        name=args.name,
        lat=args.lat,
        lng=args.lng,
        battery=args.battery,
        interval=args.interval,
    )

    if not sim.start():
        print('启动失败，请检查服务器地址和网络连接')
        sys.exit(1)

    sim.print_status()
    _interactive_loop(sim)
    print('模拟器已退出')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="TrashDet SimRobot Qt 操作台")
    parser.add_argument("--server", default="http://127.0.0.1:5000", help="后端地址")
    parser.add_argument("--device-id", default="SIM_QT_001", help="模拟设备 ID")
    return parser.parse_args(argv)



def run_gui(argv=None):
    args = parse_args(argv)
    if QT_BINDING is None:
        raise SystemExit(
            "未检测到 Qt 绑定。GUI 模式请安装 PySide6 或 PyQt6。"
        ) from _QT_IMPORT_ERROR
    app = QApplication([sys.argv[0]])
    win = SimRobotWorkbench(server=args.server, device_id=args.device_id)
    win.show()
    if hasattr(app, "exec"):
        sys.exit(app.exec())
    sys.exit(app.exec_())


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--gui", action="store_true", help="启动 Qt 图形界面")
    mode, remaining = parser.parse_known_args()
    if mode.gui:
        run_gui(remaining)
    else:
        run_cli(remaining)


if __name__ == "__main__":
    main()
