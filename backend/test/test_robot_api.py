import unittest
from datetime import datetime, timedelta
import math

from flask import Flask

from api.robot_api import robot_bp
from database.db import db
from database.models import Robot, RobotPatrolTask, User


class RobotApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SECRET_KEY': 'test-secret',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        })
        db.init_app(self.app)
        self.app.register_blueprint(robot_bp, url_prefix='/api/robot')

        with self.app.app_context():
            db.create_all()

            owner = User(username='owner_user')
            owner.set_password('password123')
            owner.set_security_code('1111')
            other_user = User(username='other_user')
            other_user.set_password('password123')
            other_user.set_security_code('2222')
            admin_user = User(username='admin_user', role='admin')
            admin_user.set_password('password123')
            admin_user.set_security_code('3333')
            db.session.add_all([owner, other_user, admin_user])
            db.session.flush()

            robot = Robot(
                device_id='R001',
                name='Robot-1',
                status='ONLINE',
                owner_user_id=owner.id,
                last_heartbeat=datetime.now(),
                next_command='STOP',
            )
            db.session.add(robot)
            db.session.commit()
            self.robot_id = robot.id
            self.owner_user_id = owner.id
            self.other_user_id = other_user.id
            self.admin_user_id = admin_user.id

        self.client = self.app.test_client()

    def _login_as(self, user_id):
        with self.client.session_transaction() as session_ctx:
            session_ctx['user_id'] = user_id

    def _distance_m(self, p1, p2):
        earth_radius = 6371000.0
        phi1 = math.radians(float(p1['lat']))
        phi2 = math.radians(float(p2['lat']))
        dphi = math.radians(float(p2['lat']) - float(p1['lat']))
        dlambda = math.radians(float(p2['lng']) - float(p1['lng']))
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return earth_radius * c

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def test_register_and_duplicate(self):
        self._login_as(self.owner_user_id)
        resp = self.client.post('/api/robot/register', json={'device_id': 'R002', 'name': 'Robot-2'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get('ok'))

        with self.app.app_context():
            created = Robot.query.filter_by(device_id='R002').first()
            self.assertIsNotNone(created)
            assert created is not None
            self.assertEqual(created.owner_user_id, self.owner_user_id)

        dup = self.client.post('/api/robot/register', json={'device_id': 'R002', 'name': 'Robot-2'})
        self.assertEqual(dup.status_code, 409)
        self.assertFalse(dup.get_json().get('ok'))

    def test_heartbeat_returns_next_command_and_uses_live_snapshot(self):
        resp = self.client.post(
            '/api/robot/heartbeat',
            json={'device_id': 'R001', 'lat': 30.555001, 'lng': 114.301002, 'battery': 88},
            headers={'X-Forwarded-For': '10.1.1.5, 192.168.1.10'}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('command'), 'STOP')

        self._login_as(self.owner_user_id)
        live_resp = self.client.get('/api/robot/live/list')
        self.assertEqual(live_resp.status_code, 200)
        live_robots = live_resp.get_json().get('robots') or []
        self.assertEqual(len(live_robots), 1)
        self.assertAlmostEqual(float(live_robots[0].get('lat')), 30.555001, places=6)
        self.assertAlmostEqual(float(live_robots[0].get('lng')), 114.301002, places=6)
        self.assertEqual(live_robots[0].get('battery'), 88)
        self.assertEqual(live_robots[0].get('ip_address'), '10.1.1.5')

        with self.app.app_context():
            robot = db.session.get(Robot, self.robot_id)
            assert robot is not None
            self.assertEqual(robot.next_command, 'IDLE')

    def test_heartbeat_always_persists_position(self):
        first = self.client.post(
            '/api/robot/heartbeat',
            json={'device_id': 'R001', 'lat': 30.701000, 'lng': 114.401000},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json().get('command'), 'STOP')

        with self.app.app_context():
            robot = db.session.get(Robot, self.robot_id)
            assert robot is not None
            self.assertAlmostEqual(float(robot.current_lat), 30.701000, places=6)
            self.assertAlmostEqual(float(robot.current_lng), 114.401000, places=6)

        second = self.client.post(
            '/api/robot/heartbeat',
            json={'device_id': 'R001', 'lat': 30.702000, 'lng': 114.402000},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json().get('command'), 'IDLE')

        with self.app.app_context():
            robot = db.session.get(Robot, self.robot_id)
            assert robot is not None
            self.assertAlmostEqual(float(robot.current_lat), 30.702000, places=6)
            self.assertAlmostEqual(float(robot.current_lng), 114.402000, places=6)

    def test_control_alias_command(self):
        self._login_as(self.owner_user_id)
        resp = self.client.post('/api/robot/control', json={'id': self.robot_id, 'command': 'backward'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get('command'), 'BACK')

        with self.app.app_context():
            robot = db.session.get(Robot, self.robot_id)
            assert robot is not None
            self.assertEqual(robot.next_command, 'BACK')

    def test_navigate_invalid_coordinate(self):
        self._login_as(self.owner_user_id)
        resp = self.client.post('/api/robot/navigate', json={'id': self.robot_id, 'lat': 99.0, 'lng': 120.0})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json().get('ok'))

    def test_list_marks_robot_offline_when_timeout(self):
        self._login_as(self.owner_user_id)
        with self.app.app_context():
            robot = db.session.get(Robot, self.robot_id)
            assert robot is not None
            robot.last_heartbeat = datetime.now() - timedelta(seconds=100)
            robot.status = 'ONLINE'
            db.session.commit()

        resp = self.client.get('/api/robot/list')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get('ok'))
        robots = payload.get('robots') or []
        self.assertEqual(robots[0].get('status'), 'OFFLINE')

    def test_non_owner_cannot_control_robot(self):
        self._login_as(self.other_user_id)
        resp = self.client.post('/api/robot/control', json={'id': self.robot_id, 'command': 'STOP'})
        self.assertEqual(resp.status_code, 403)

    def test_non_owner_cannot_list_owner_robots(self):
        self._login_as(self.other_user_id)
        resp = self.client.get('/api/robot/list')
        self.assertEqual(resp.status_code, 200)
        robots = resp.get_json().get('robots') or []
        self.assertEqual(len(robots), 0)

    def test_admin_can_list_all_robots(self):
        self._login_as(self.admin_user_id)
        resp = self.client.get('/api/robot/list')
        self.assertEqual(resp.status_code, 200)
        robots = resp.get_json().get('robots') or []
        self.assertEqual(len(robots), 1)

    def test_patrol_task_crud_flow(self):
        self._login_as(self.owner_user_id)
        create_resp = self.client.post(
            '/api/robot/task/create',
            json={
                'robot_id': self.robot_id,
                'name': 'Morning Patrol',
                'inspection_area': [
                    {'lat': 30.1, 'lng': 120.1},
                    {'lat': 30.2, 'lng': 120.2},
                    {'lat': 30.3, 'lng': 120.3},
                ],
                'planned_path': [
                    {'lat': 30.11, 'lng': 120.11},
                    {'lat': 30.22, 'lng': 120.22},
                ],
                'status': 'PLANNED',
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        task = create_resp.get_json().get('task')
        self.assertIsNotNone(task)
        assert task is not None
        task_id = task.get('id')

        list_resp = self.client.get(f'/api/robot/task/list?robot_id={self.robot_id}')
        self.assertEqual(list_resp.status_code, 200)
        tasks = list_resp.get_json().get('tasks') or []
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].get('name'), 'Morning Patrol')

        get_resp = self.client.get(f'/api/robot/task/{task_id}')
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.get_json().get('task', {}).get('status'), 'PLANNED')

        update_resp = self.client.post(
            f'/api/robot/task/update/{task_id}',
            json={'status': 'RUNNING', 'planned_path': [{'lat': 30.33, 'lng': 120.33}, {'lat': 30.44, 'lng': 120.44}]},
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.get_json().get('task', {}).get('status'), 'RUNNING')

        delete_resp = self.client.post(f'/api/robot/task/delete/{task_id}', json={})
        self.assertEqual(delete_resp.status_code, 200)

        with self.app.app_context():
            deleted = db.session.get(RobotPatrolTask, task_id)
            self.assertIsNone(deleted)

    def test_patrol_task_owner_permission(self):
        with self.app.app_context():
            task = RobotPatrolTask(
                robot_id=self.robot_id,
                name='Protected Patrol',
                inspection_area='[{"lat":30.1,"lng":120.1},{"lat":30.2,"lng":120.2},{"lat":30.3,"lng":120.3}]',
                planned_path='[{"lat":30.11,"lng":120.11},{"lat":30.22,"lng":120.22}]',
                status='PLANNED',
                created_by_user_id=self.owner_user_id,
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.id

        self._login_as(self.other_user_id)
        forbidden_resp = self.client.get(f'/api/robot/task/{task_id}')
        self.assertEqual(forbidden_resp.status_code, 403)

        self._login_as(self.admin_user_id)
        admin_resp = self.client.get(f'/api/robot/task/{task_id}')
        self.assertEqual(admin_resp.status_code, 200)

    def test_patrol_task_defaults_to_paused_and_can_finish_after_manual_start(self):
        self._login_as(self.owner_user_id)
        path_points = [
            {'lat': 30.211100, 'lng': 120.211100},
            {'lat': 30.211300, 'lng': 120.211300},
        ]

        create_resp = self.client.post(
            '/api/robot/task/create',
            json={
                'robot_id': self.robot_id,
                'name': 'Paused By Default',
                'inspection_area': [
                    {'lat': 30.1, 'lng': 120.1},
                    {'lat': 30.2, 'lng': 120.2},
                    {'lat': 30.3, 'lng': 120.3},
                ],
                'planned_path': path_points,
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created_task = create_resp.get_json().get('task', {})
        task_id = created_task.get('id')
        self.assertIsNotNone(task_id)
        self.assertEqual(created_task.get('status'), 'PAUSED')

        with self.app.app_context():
            task = db.session.get(RobotPatrolTask, task_id)
            assert task is not None
            self.assertEqual(task.status, 'PAUSED')

        run_resp = self.client.post(f'/api/robot/task/update/{task_id}', json={'status': 'RUNNING'})
        self.assertEqual(run_resp.status_code, 200)
        self.assertEqual(run_resp.get_json().get('task', {}).get('status'), 'RUNNING')

        first_heartbeat = self.client.post(
            '/api/robot/heartbeat',
            json={'device_id': 'R001', 'lat': 30.211100, 'lng': 120.211100},
        )
        self.assertEqual(first_heartbeat.status_code, 200)
        self.assertEqual(first_heartbeat.get_json().get('command'), 'NAVIGATE')

        second_heartbeat = self.client.post(
            '/api/robot/heartbeat',
            json={'device_id': 'R001', 'lat': 30.211300, 'lng': 120.211300},
        )
        self.assertEqual(second_heartbeat.status_code, 200)

        with self.app.app_context():
            task = db.session.get(RobotPatrolTask, task_id)
            assert task is not None
            self.assertEqual(task.status, 'DONE')
            self.assertEqual(int(task.current_waypoint_index or 0), len(path_points))

    def test_running_patrol_auto_dispatch_and_finish(self):
        self._login_as(self.owner_user_id)
        path_points = [
            {'lat': 30.111100, 'lng': 120.111100},
            {'lat': 30.111300, 'lng': 120.111300},
            {'lat': 30.111500, 'lng': 120.111500},
            {'lat': 30.111700, 'lng': 120.111700},
        ]
        create_resp = self.client.post(
            '/api/robot/task/create',
            json={
                'robot_id': self.robot_id,
                'name': 'Auto Patrol',
                'inspection_area': [
                    {'lat': 30.1, 'lng': 120.1},
                    {'lat': 30.2, 'lng': 120.2},
                    {'lat': 30.3, 'lng': 120.3},
                ],
                'planned_path': path_points,
                'status': 'RUNNING',
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        created_task = create_resp.get_json().get('task', {})
        task_id = created_task.get('id')
        self.assertIsNotNone(task_id)
        self.assertEqual(int(created_task.get('total_waypoints') or 0), len(path_points))

        first_heartbeat = self.client.post(
            '/api/robot/heartbeat',
            json={'device_id': 'R001', 'lat': 30.111100, 'lng': 120.111100},
        )
        self.assertEqual(first_heartbeat.status_code, 200)
        first_payload = first_heartbeat.get_json()
        self.assertEqual(first_payload.get('command'), 'NAVIGATE')
        target = first_payload.get('target') or {}
        self.assertIsNotNone(target.get('lat'))
        self.assertIsNotNone(target.get('lng'))
        self.assertLess(
            self._distance_m(target, path_points[1]),
            2.5,
        )

        expected_targets = path_points[2:]
        for index, point in enumerate(path_points[1:], start=1):
            heartbeat_resp = self.client.post(
                '/api/robot/heartbeat',
                json={'device_id': 'R001', 'lat': point['lat'], 'lng': point['lng']},
            )
            self.assertEqual(heartbeat_resp.status_code, 200)
            hb_payload = heartbeat_resp.get_json()
            if index - 1 < len(expected_targets):
                expected_target = expected_targets[index - 1]
                got_target = hb_payload.get('target') or {}
                self.assertEqual(hb_payload.get('command'), 'NAVIGATE')
                self.assertLess(self._distance_m(got_target, expected_target), 2.5)

        with self.app.app_context():
            task = db.session.get(RobotPatrolTask, task_id)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.status, 'DONE')
            self.assertEqual(int(task.current_waypoint_index or 0), len(path_points))


if __name__ == '__main__':
    unittest.main()
