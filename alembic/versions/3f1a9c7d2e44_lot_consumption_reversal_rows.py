"""lot consumption reversal rows (append-only) + backfill of historic reversed sales

Revision ID: 3f1a9c7d2e44
Revises: 95dc0d4f29fa
Create Date: 2026-10-02 21:30:00.000000

عكس/تعديل قيد استهلك من دفعة رمبي لم يكن يعيد الكمية ولا يعكس صف الاستهلاك — المخزون يضيع بصمت
(اكتُشف أثناء تحقيق LOT-2026-0108). يضيف عموداً `reverses_consumption_id` (صف عكسي append-only)،
ثم **يرحّل البيانات التاريخية**: كل استهلاك قيده REVERSED بلا صف عكسي يُعطى صفاً عكسياً وتُعاد
كميته لدفعته (وتُعاد فتح الدفعة المقفلة التي صار لها رصيد).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3f1a9c7d2e44'
down_revision: Union[str, None] = '95dc0d4f29fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def backfill_historic_reversals(bind) -> int:
    """يُنشئ الصفوف العكسية الناقصة ويعيد كمياتها. يُعيد عدد الصفوف المُضافة (idempotent)."""
    rows = bind.execute(sa.text("""
        SELECT c.id, c.lot_id, e.reversed_by_entry_id, c.qty, c.client_rate, c.cost_share, c.revenue, c.profit,
               c.profit_currency
        FROM lot_consumptions c
        JOIN journal_entries e ON e.id = c.entry_id
        WHERE c.reverses_consumption_id IS NULL
          AND e.status = 'REVERSED' AND e.reversed_by_entry_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM lot_consumptions r WHERE r.reverses_consumption_id = c.id)
    """)).all()
    for cid, lot_id, rev_entry, qty, rate, cost, revenue, profit, ccy in rows:
        bind.execute(sa.text("""
            INSERT INTO lot_consumptions
                (lot_id, entry_id, qty, client_rate, cost_share, revenue, profit, profit_currency, consumed_at,
                 reverses_consumption_id)
            VALUES (:lot, :entry, :qty, :rate, :cost, :revenue, :profit, :ccy, now(), :orig)
        """), {"lot": lot_id, "entry": rev_entry, "qty": qty, "rate": rate, "cost": -cost, "revenue": -revenue,
               "profit": -profit, "ccy": ccy, "orig": cid})
        bind.execute(sa.text("UPDATE currency_lots SET remaining_qty = remaining_qty + :q WHERE id = :l"),
                     {"q": qty, "l": lot_id})
    if rows:
        bind.execute(sa.text("""
            UPDATE currency_lots l SET status = 'OPEN', closed_at = NULL
            WHERE l.status = 'CLOSED' AND l.remaining_qty > 0
              AND NOT EXISTS (SELECT 1 FROM journal_entries s WHERE s.id = l.source_entry_id AND s.status = 'REVERSED')
        """))
    return len(rows)


def upgrade() -> None:
    op.add_column('lot_consumptions', sa.Column('reverses_consumption_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_lot_consumptions_reverses', 'lot_consumptions', 'lot_consumptions',
                          ['reverses_consumption_id'], ['id'])
    op.create_index('uq_lot_consumptions_reverses', 'lot_consumptions', ['reverses_consumption_id'], unique=True,
                    postgresql_where=sa.text('reverses_consumption_id IS NOT NULL'))
    backfill_historic_reversals(op.get_bind())


def downgrade() -> None:
    # الصفوف العكسية تُحذف وتُخصَم كمياتها من الدفعات (عودة لحالة ما قبل العكس)
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE currency_lots l SET remaining_qty = l.remaining_qty - r.q
        FROM (SELECT lot_id, SUM(qty) AS q FROM lot_consumptions WHERE reverses_consumption_id IS NOT NULL GROUP BY lot_id) r
        WHERE l.id = r.lot_id
    """))
    bind.execute(sa.text("DELETE FROM lot_consumptions WHERE reverses_consumption_id IS NOT NULL"))
    op.drop_index('uq_lot_consumptions_reverses', table_name='lot_consumptions',
                  postgresql_where=sa.text('reverses_consumption_id IS NOT NULL'))
    op.drop_constraint('fk_lot_consumptions_reverses', 'lot_consumptions', type_='foreignkey')
    op.drop_column('lot_consumptions', 'reverses_consumption_id')
