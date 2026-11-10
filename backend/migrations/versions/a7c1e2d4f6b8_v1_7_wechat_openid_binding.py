"""v1.7 wechat openid binding

给 users 加 wechat_openid（扫码绑定后免密登录），给 wechat_scenes 加 openid
（微信回调事件带的来源 openid，用于首次绑定）。

Revision ID: a7c1e2d4f6b8
Revises: ff5854424543
Create Date: 2026-11-10 07:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c1e2d4f6b8'
down_revision = 'ff5854424543'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('wechat_openid', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_users_wechat_openid'), 'users', ['wechat_openid'], unique=True)
    op.add_column('wechat_scenes', sa.Column('openid', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_wechat_scenes_openid'), 'wechat_scenes', ['openid'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_wechat_scenes_openid'), table_name='wechat_scenes')
    op.drop_column('wechat_scenes', 'openid')
    op.drop_index(op.f('ix_users_wechat_openid'), table_name='users')
    op.drop_column('users', 'wechat_openid')
