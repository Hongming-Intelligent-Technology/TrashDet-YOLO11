"""Add train_jobs table for persisted training job state

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-04

"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'train_jobs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.String(length=32), nullable=True),
        sa.Column('started_at', sa.String(length=32), nullable=True),
        sa.Column('completed_at', sa.String(length=32), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('meta_json', sa.Text(), nullable=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('logs_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('train_jobs')
