"""user_backup_codes — رموز احتياطية للمصادقة الثنائية

Revision ID: a4c8e1f27d63
Revises: 7b2d4e6f8a10
Create Date: 2026-10-03 10:00:00.000000

عشرة رموز لمرة واحدة بدل رمز تطبيق المصادقة؛ تُخزَّن هاشاً فقط.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4c8e1f27d63'
down_revision: Union[str, None] = '7b2d4e6f8a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_backup_codes',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('code_hash', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invalidated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_backup_codes_user', 'user_backup_codes', ['user_id'], unique=False)
    op.create_index('uq_user_backup_codes_live_hash', 'user_backup_codes', ['user_id', 'code_hash'], unique=True,
                    postgresql_where=sa.text('used_at IS NULL AND invalidated_at IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_user_backup_codes_live_hash', table_name='user_backup_codes',
                  postgresql_where=sa.text('used_at IS NULL AND invalidated_at IS NULL'))
    op.drop_index('ix_user_backup_codes_user', table_name='user_backup_codes')
    op.drop_table('user_backup_codes')
