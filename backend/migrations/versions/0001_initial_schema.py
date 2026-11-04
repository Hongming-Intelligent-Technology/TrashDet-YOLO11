"""Initial schema (baseline matching the models before migrations were introduced)

Databases created earlier by db.create_all() or database.sql are stamped at
this revision automatically on first startup (see apply_database_migrations_impl).

Revision ID: 0001
Revises:
Create Date: 2026-11-04

"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('security_code', sa.String(length=255), nullable=False),
        sa.Column('organization', sa.String(length=120), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )

    op.create_table(
        'robots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('device_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('owner_user_id', sa.Integer(), nullable=True),
        sa.Column('current_lat', sa.Float(), nullable=True),
        sa.Column('current_lng', sa.Float(), nullable=True),
        sa.Column('target_lat', sa.Float(), nullable=True),
        sa.Column('target_lng', sa.Float(), nullable=True),
        sa.Column('last_heartbeat', sa.DateTime(), nullable=True),
        sa.Column('next_command', sa.String(length=100), nullable=True),
        sa.Column('battery', sa.Integer(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id'),
    )
    op.create_index(op.f('ix_robots_owner_user_id'), 'robots', ['owner_user_id'], unique=False)

    op.create_table(
        'detection_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=20), nullable=True),
        sa.Column('source_path', sa.String(length=255), nullable=True),
        sa.Column('result_path', sa.String(length=255), nullable=True),
        sa.Column('device_id', sa.String(length=50), nullable=True),
        sa.Column('location', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('error_msg', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_detection_tasks_user_id'), 'detection_tasks', ['user_id'], unique=False)
    op.create_index(op.f('ix_detection_tasks_created_at'), 'detection_tasks', ['created_at'], unique=False)
    op.create_index(op.f('ix_detection_tasks_latitude'), 'detection_tasks', ['latitude'], unique=False)

    op.create_table(
        'detection_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('label', sa.String(length=50), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('x1', sa.Integer(), nullable=True),
        sa.Column('y1', sa.Integer(), nullable=True),
        sa.Column('x2', sa.Integer(), nullable=True),
        sa.Column('y2', sa.Integer(), nullable=True),
        sa.Column('area', sa.Integer(), nullable=True),
        sa.Column('handle_state', sa.String(length=20), nullable=True),
        sa.Column('frame_index', sa.Integer(), nullable=True),
        sa.Column('snapshot_path', sa.String(length=255), nullable=True),
        sa.Column('captured_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['detection_tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_detection_items_task_id'), 'detection_items', ['task_id'], unique=False)
    op.create_index(op.f('ix_detection_items_label'), 'detection_items', ['label'], unique=False)

    op.create_table(
        'operation_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'robot_patrol_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('robot_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('inspection_area', sa.Text(), nullable=False),
        sa.Column('planned_path', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('current_waypoint_index', sa.Integer(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['robot_id'], ['robots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_robot_patrol_tasks_robot_id'), 'robot_patrol_tasks', ['robot_id'], unique=False)
    op.create_index(
        op.f('ix_robot_patrol_tasks_created_by_user_id'), 'robot_patrol_tasks', ['created_by_user_id'], unique=False
    )
    op.create_index(op.f('ix_robot_patrol_tasks_created_at'), 'robot_patrol_tasks', ['created_at'], unique=False)


def downgrade():
    op.drop_table('robot_patrol_tasks')
    op.drop_table('operation_logs')
    op.drop_table('detection_items')
    op.drop_table('detection_tasks')
    op.drop_table('robots')
    op.drop_table('users')
