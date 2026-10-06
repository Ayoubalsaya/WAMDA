"""sessions.last_seen_at — مهلة الخمول

Revision ID: c1d3e5f7a9b0
Revises: b9c1e3f5a7d8
Create Date: 2026-10-06 12:00:00.000000

الجلسات القائمة وقت الترحيل تأخذ `now()` (تبدأ مهلة خمولها من لحظة الترحيل).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d3e5f7a9b0'
down_revision: Union[str, None] = 'b9c1e3f5a7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))


def downgrade() -> None:
    op.drop_column('sessions', 'last_seen_at')
