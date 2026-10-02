"""credit limit positive — «حد بمبلغ صفر» بلا معنى: يتحول إلى NONE ويُمنع LIMIT بمبلغ ≤ 0

Revision ID: e6f8b0c2d4a5
Revises: d5e7a9b1c3f4
Create Date: 2026-10-03 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e6f8b0c2d4a5'
down_revision: Union[str, None] = 'd5e7a9b1c3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ترحيل d5e7a9b1c3f4 حوّل credit_allowed=true بلا حد إلى LIMIT 0؛ حدّ صفر ≡ بلا ائتمان فيُوحَّد في NONE
    op.execute("UPDATE client_credit_limits SET mode = 'NONE', limit_amount = NULL WHERE mode = 'LIMIT' AND limit_amount <= 0")
    op.drop_constraint('ck_client_credit_limits_nonneg', 'client_credit_limits', type_='check')
    op.create_check_constraint('ck_client_credit_limits_positive', 'client_credit_limits', 'limit_amount IS NULL OR limit_amount > 0')


def downgrade() -> None:
    op.drop_constraint('ck_client_credit_limits_positive', 'client_credit_limits', type_='check')
    op.create_check_constraint('ck_client_credit_limits_nonneg', 'client_credit_limits', 'limit_amount IS NULL OR limit_amount >= 0')
