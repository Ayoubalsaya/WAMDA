"""credit modes — ائتمان بلا سقف: وضع صريح لكل عميل × عملة، وحذف clients.credit_allowed

Revision ID: d5e7a9b1c3f4
Revises: a4c8e1f27d63
Create Date: 2026-10-03 14:00:00.000000

القديم: `clients.credit_allowed` (علم واحد) + `client_credit_limits.limit_amount` (حد لكل عملة، غياب الصف = حد صفر).
الجديد: `mode` ∈ {NONE, LIMIT, UNLIMITED} لكل (عميل، عملة)؛ غياب الصف = NONE.
التحويل يحفظ السلوك الفعلي: credit_allowed=true وحد > 0 ← LIMIT؛ credit_allowed=true وحد 0 ← LIMIT 0 (يبقى مساره
تجاوز المدير بسبب)؛ credit_allowed=false ← NONE (كان يُرفض كلياً بلا تجاوز). لا UNLIMITED تلقائياً أبداً.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e7a9b1c3f4'
down_revision: Union[str, None] = 'a4c8e1f27d63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('client_credit_limits', sa.Column('mode', sa.Text(), server_default='LIMIT', nullable=False))
    op.alter_column('client_credit_limits', 'limit_amount', existing_type=sa.Numeric(20, 6), nullable=True)
    # عميل بلا ائتمان مسموح: كل صفوف حدوده تصير NONE (كان الرفض تاماً مهما كان الحد)
    op.execute("""
        UPDATE client_credit_limits l SET mode = 'NONE', limit_amount = NULL
        FROM clients c WHERE c.id = l.client_id AND c.credit_allowed = false
    """)
    # عميل مسموح الائتمان بلا صف حد في عملة: كان حدّه صفراً (مسار تجاوز المدير) — يُنشأ LIMIT 0 لكل عملة فعّالة
    op.execute("""
        INSERT INTO client_credit_limits (client_id, currency_code, mode, limit_amount)
        SELECT c.id, cur.code, 'LIMIT', 0 FROM clients c CROSS JOIN currencies cur
        WHERE c.credit_allowed = true AND cur.is_active = true
          AND NOT EXISTS (SELECT 1 FROM client_credit_limits l WHERE l.client_id = c.id AND l.currency_code = cur.code)
    """)
    op.drop_constraint('ck_client_credit_limits_nonneg', 'client_credit_limits', type_='check')
    op.create_check_constraint('ck_client_credit_limits_nonneg', 'client_credit_limits', 'limit_amount IS NULL OR limit_amount >= 0')
    op.create_check_constraint('ck_client_credit_limits_mode', 'client_credit_limits', "mode IN ('NONE', 'LIMIT', 'UNLIMITED')")
    op.create_check_constraint(
        'ck_client_credit_limits_limit_iff_limit_mode', 'client_credit_limits', "(mode = 'LIMIT') = (limit_amount IS NOT NULL)")
    op.drop_column('clients', 'credit_allowed')


def downgrade() -> None:
    op.add_column('clients', sa.Column('credit_allowed', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute("""
        UPDATE clients c SET credit_allowed = true
        WHERE EXISTS (SELECT 1 FROM client_credit_limits l WHERE l.client_id = c.id AND l.mode IN ('LIMIT', 'UNLIMITED'))
    """)
    op.drop_constraint('ck_client_credit_limits_limit_iff_limit_mode', 'client_credit_limits', type_='check')
    op.drop_constraint('ck_client_credit_limits_mode', 'client_credit_limits', type_='check')
    op.drop_constraint('ck_client_credit_limits_nonneg', 'client_credit_limits', type_='check')
    op.execute("DELETE FROM client_credit_limits WHERE mode = 'NONE'")
    op.execute("UPDATE client_credit_limits SET limit_amount = 0 WHERE mode = 'UNLIMITED'")
    op.alter_column('client_credit_limits', 'limit_amount', existing_type=sa.Numeric(20, 6), nullable=False)
    op.create_check_constraint('ck_client_credit_limits_nonneg', 'client_credit_limits', 'limit_amount >= 0')
    op.drop_column('client_credit_limits', 'mode')
