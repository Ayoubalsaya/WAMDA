"""drop security question — حذف أعمدة سؤال الأمان وتجزئة إجاباته (استعادة كلمة المرور بسؤال الأمان أُزيلت)

Revision ID: b9c1e3f5a7d8
Revises: a8b0d2e4f6c7
Create Date: 2026-10-06 12:00:00.000000

المسارات `/auth/recover/*` و`/portal/recover/*` حُذفت (تدقيق U-01: بلا حدّ ولا إبطال جلسات، تتيح الاستيلاء على حساب عميل). الأعمدة
لم يعد يقرؤها أحد؛ إبقاء تجزئات الإجابات يزيد سطح الكشف بلا فائدة. البدائل: دعوات البوابة (`portal/reset`) والرموز الاحتياطية
وأوامر الخادم. التراجع يعيد الأعمدة فارغة (القيم لا تُستعاد).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b9c1e3f5a7d8'
down_revision: Union[str, None] = 'a8b0d2e4f6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('users', 'security_question')
    op.drop_column('users', 'security_answer_hash')
    op.drop_column('clients', 'portal_security_question')
    op.drop_column('clients', 'portal_security_answer_hash')


def downgrade() -> None:
    op.add_column('clients', sa.Column('portal_security_answer_hash', sa.Text(), nullable=True))
    op.add_column('clients', sa.Column('portal_security_question', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('security_answer_hash', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('security_question', sa.Text(), nullable=True))
