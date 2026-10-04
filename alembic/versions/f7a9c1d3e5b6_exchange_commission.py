"""exchange commission — عمولة اختيارية على الصرافة: أعمدة مرجعية على القيد (المبلغ · العملة · الاتجاه)

Revision ID: f7a9c1d3e5b6
Revises: e6f8b0c2d4a5
Create Date: 2026-10-04 16:00:00.000000

العمولة زوج أسطر متوازن بعملتها (4110/5410 بفروعها)؛ هذه الأعمدة مرجع للتقارير والإيصال، ويطابقها `recompute.verify` مع الأسطر الفعلية.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a9c1d3e5b6'
down_revision: Union[str, None] = 'e6f8b0c2d4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('journal_entries', sa.Column('commission_amount', sa.Numeric(20, 6), nullable=True))
    op.add_column('journal_entries', sa.Column('commission_currency', sa.Text(), nullable=True))
    op.add_column('journal_entries', sa.Column('commission_direction', sa.Text(), nullable=True))
    op.create_foreign_key('fk_journal_entries_commission_currency', 'journal_entries', 'currencies', ['commission_currency'], ['code'])
    op.create_check_constraint(
        'ck_journal_entries_commission_all_or_none', 'journal_entries',
        "(commission_amount IS NULL AND commission_currency IS NULL AND commission_direction IS NULL) OR "
        "(commission_amount > 0 AND commission_currency IS NOT NULL AND commission_direction IN ('IN', 'OUT'))",
    )


def downgrade() -> None:
    op.drop_constraint('ck_journal_entries_commission_all_or_none', 'journal_entries', type_='check')
    op.drop_constraint('fk_journal_entries_commission_currency', 'journal_entries', type_='foreignkey')
    op.drop_column('journal_entries', 'commission_direction')
    op.drop_column('journal_entries', 'commission_currency')
    op.drop_column('journal_entries', 'commission_amount')
