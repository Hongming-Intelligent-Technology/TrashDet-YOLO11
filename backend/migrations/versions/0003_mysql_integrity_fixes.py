"""Integrity and precision fixes (foreign keys, DOUBLE coordinates, wider location)

- coordinates become DOUBLE (SQLAlchemy Float is single-precision FLOAT on MySQL, ~1 m error)
- detection_tasks.location widened to 255 characters
- users.role NOT NULL DEFAULT 'user'
- detection_items.task_id NOT NULL with ON DELETE CASCADE
- owner/creator user columns reference users.id with ON DELETE SET NULL
- index on robot_patrol_tasks (robot_id, status)

Works on databases created by db.create_all(), by migration 0001, or by the old
database/database.sql: existing foreign keys are looked up by column and replaced.
Rows that would violate the new constraints are cleaned first (orphaned owner ids
are set to NULL, detection items without a task are deleted).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04

"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

# Gives unnamed foreign keys (SQLite) a predictable name so batch mode can drop them.
NAMING_CONVENTION = {'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'}

# (table, column, referred table, new constraint name, ON DELETE)
USER_REFERENCES = [
    ('detection_tasks', 'user_id', 'users', 'fk_detection_tasks_user_id', 'SET NULL'),
    ('robots', 'owner_user_id', 'users', 'fk_robots_owner_user_id', 'SET NULL'),
    ('robot_patrol_tasks', 'created_by_user_id', 'users', 'fk_robot_patrol_tasks_created_by_user_id', 'SET NULL'),
    ('operation_logs', 'user_id', 'users', 'fk_operation_logs_user_id', 'SET NULL'),
]
ITEM_TASK_FK = ('detection_items', 'task_id', 'detection_tasks', 'fk_detection_items_task_id', 'CASCADE')

DOUBLE_COLUMNS = {
    'detection_tasks': ['latitude', 'longitude'],
    'robots': ['current_lat', 'current_lng', 'target_lat', 'target_lng'],
}

PATROL_STATUS_INDEX = 'ix_robot_patrol_tasks_robot_id_status'


def _existing_fk_names(inspector, table, column):
    names = []
    for fk in inspector.get_foreign_keys(table):
        if fk.get('constrained_columns') == [column]:
            names.append(fk.get('name') or NAMING_CONVENTION['fk'] % {
                'table_name': table,
                'column_0_name': column,
                'referred_table_name': fk.get('referred_table'),
            })
    return names


def _clean_data():
    op.execute("UPDATE users SET role = 'user' WHERE role IS NULL")
    op.execute(
        'DELETE FROM detection_items '
        'WHERE task_id IS NULL OR task_id NOT IN (SELECT id FROM detection_tasks)'
    )
    for table, column, referred, _name, _ondelete in USER_REFERENCES:
        op.execute(
            f'UPDATE {table} SET {column} = NULL '
            f'WHERE {column} IS NOT NULL AND {column} NOT IN (SELECT id FROM {referred})'
        )


def upgrade():
    _clean_data()
    inspector = sa.inspect(op.get_bind())

    with op.batch_alter_table('users') as batch:
        batch.alter_column(
            'role',
            existing_type=sa.String(length=20),
            nullable=False,
            server_default='user',
        )

    with op.batch_alter_table('detection_tasks', naming_convention=NAMING_CONVENTION) as batch:
        batch.alter_column('location', existing_type=sa.String(length=100), type_=sa.String(length=255), existing_nullable=True)
        for column in DOUBLE_COLUMNS['detection_tasks']:
            batch.alter_column(column, existing_type=sa.Float(), type_=sa.Double(), existing_nullable=True)

    with op.batch_alter_table('robots', naming_convention=NAMING_CONVENTION) as batch:
        for column in DOUBLE_COLUMNS['robots']:
            batch.alter_column(column, existing_type=sa.Float(), type_=sa.Double(), existing_nullable=True)

    table, column, referred, name, ondelete = ITEM_TASK_FK
    with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch:
        for old_name in _existing_fk_names(inspector, table, column):
            batch.drop_constraint(old_name, type_='foreignkey')
        batch.alter_column(column, existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(name, referred, [column], ['id'], ondelete=ondelete)

    for table, column, referred, name, ondelete in USER_REFERENCES:
        with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch:
            for old_name in _existing_fk_names(inspector, table, column):
                batch.drop_constraint(old_name, type_='foreignkey')
            batch.create_foreign_key(name, referred, [column], ['id'], ondelete=ondelete)

    patrol_indexes = inspector.get_indexes('robot_patrol_tasks')
    if not any(index.get('column_names') == ['robot_id', 'status'] for index in patrol_indexes):
        op.create_index(PATROL_STATUS_INDEX, 'robot_patrol_tasks', ['robot_id', 'status'], unique=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if any(index.get('name') == PATROL_STATUS_INDEX for index in inspector.get_indexes('robot_patrol_tasks')):
        op.drop_index(PATROL_STATUS_INDEX, table_name='robot_patrol_tasks')

    for table, _column, _referred, name, _ondelete in USER_REFERENCES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_='foreignkey')

    table, column, referred, name, _ondelete = ITEM_TASK_FK
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(name, type_='foreignkey')
        batch.alter_column(column, existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key('fk_detection_items_task_id_detection_tasks', referred, [column], ['id'])

    with op.batch_alter_table('robots') as batch:
        for column in DOUBLE_COLUMNS['robots']:
            batch.alter_column(column, existing_type=sa.Double(), type_=sa.Float(), existing_nullable=True)

    with op.batch_alter_table('detection_tasks') as batch:
        for column in DOUBLE_COLUMNS['detection_tasks']:
            batch.alter_column(column, existing_type=sa.Double(), type_=sa.Float(), existing_nullable=True)
        batch.alter_column('location', existing_type=sa.String(length=255), type_=sa.String(length=100), existing_nullable=True)

    with op.batch_alter_table('users') as batch:
        batch.alter_column('role', existing_type=sa.String(length=20), nullable=True, server_default=None)
