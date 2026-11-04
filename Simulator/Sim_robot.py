import argparse
import math
import os
import sys
import threading
import time

import requests

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
║              EcoGuard 机器人交互式模拟器                 ║
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

        if command == 'STOP':
            with self._lock:
                self._moving = None
                self._nav_target = None
            _info('服务器指令: STOP — 已停止')
            return

        if command == 'PAUSE':
            with self._lock:
                self._paused = True
            _info('服务器指令: PAUSE — 已暂停')
            return

        if command == 'RESUME':
            with self._lock:
                self._paused = False
            _info('服务器指令: RESUME — 已恢复')
            return

        if command == 'RETURN_HOME':
            _info('服务器指令: RETURN_HOME — 返航中（模拟）')
            return

        if command == 'PICK_TRASH':
            _info('服务器指令: PICK_TRASH — 正在抓取垃圾（模拟）')
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


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def run_cli():
    parser = argparse.ArgumentParser(
        description='EcoGuard 机器人交互式终端模拟器',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--server',   default='http://127.0.0.1:5000', help='服务器地址')
    parser.add_argument('--id',       default='SIM_ROBOT_001',         help='设备 ID')
    parser.add_argument('--name',     default='Simulator',             help='设备名称')
    parser.add_argument('--lat',      type=float, default=30.5,        help='初始纬度')
    parser.add_argument('--lng',      type=float, default=114.3,       help='初始经度')
    parser.add_argument('--battery',  type=float, default=90.0,        help='初始电量 (0-100)')
    parser.add_argument('--interval', type=float, default=0.5,         help='心跳间隔（秒）')
    args = parser.parse_args()

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


if __name__ == '__main__':
    run_cli()
