"""fn_normalize_arabic: trim leading/trailing spaces; refresh clients.search_name

Revision ID: 7b2d4e6f8a10
Revises: 3f1a9c7d2e44
Create Date: 2026-10-02 23:00:00.000000

توحيد الكتابة العربية للبحث ومنع تكرار العملاء: الدالة الأصلية تزيل التشكيل والتطويل وتوحّد أ/إ/آ/ٱ→ا و ة→ه
و ى→ي و ؤ→و و ئ→ي وتطوي المسافات المتعددة، لكنها لا تقصّ المسافات الطرفية — فيُعدّ «أحمد » و«أحمد» اسمين
مختلفين. تُضاف `btrim` ويُعاد حساب `search_name` لكل العملاء.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '7b2d4e6f8a10'
down_revision: Union[str, None] = '3f1a9c7d2e44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW = r"""
CREATE OR REPLACE FUNCTION fn_normalize_arabic(p_text TEXT) RETURNS TEXT AS $$
    SELECT btrim(regexp_replace(
             translate(
               regexp_replace(coalesce(p_text, ''), '[ً-ْـ]', '', 'g'),
               'أإآٱةىؤئ',
               'ااااهيوي'
             ),
           '\s+', ' ', 'g'))
$$ LANGUAGE sql IMMUTABLE;
"""
_OLD = r"""
CREATE OR REPLACE FUNCTION fn_normalize_arabic(p_text TEXT) RETURNS TEXT AS $$
    SELECT regexp_replace(
             translate(
               regexp_replace(coalesce(p_text, ''), '[ً-ْـ]', '', 'g'),
               'أإآٱةىؤئ',
               'ااااهيوي'
             ),
           '\s+', ' ', 'g')
$$ LANGUAGE sql IMMUTABLE;
"""


def upgrade() -> None:
    op.execute(_NEW)
    op.execute("UPDATE clients SET search_name = fn_normalize_arabic(name_ar)")


def downgrade() -> None:
    op.execute(_OLD)
    op.execute("UPDATE clients SET search_name = fn_normalize_arabic(name_ar)")
