"""entry source request — طلب الإنشاء الأصلي يُحفظ مع القيد ليفتح التعديل مملوءاً بقيمه

Revision ID: a8b0d2e4f6c7
Revises: f7a9c1d3e5b6
Create Date: 2026-10-04 20:00:00.000000

نموذج التعديل كان يفتح فارغاً فيضيع ما لا يعيد المستخدم إدخاله (عمولة، ملاحظة، موقع…). الآن يُحفظ جسم طلب الإنشاء (بعد التحقق)
على القيد، ويفتح التعديل به. القيود السابقة بلا طلب محفوظ (NULL) — يظهر لها تنبيه بدل تعبئة مضلِّلة.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a8b0d2e4f6c7'
down_revision: Union[str, None] = 'f7a9c1d3e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('journal_entries', sa.Column('source_request', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('journal_entries', 'source_request')
