"""drop_beneficiaries — قرار مالك ٢٠٢٦-٠٩-٢٢: إلغاء سجل المستفيدين بالكامل.

٩٥٪ من العملاء يعطون رقم حساب فقط بلا معلومة أخرى، وحقل ملاحظة القيد
(`journal_entries.note`، المرحلة ١٤ب) يكفي لتدوين الوجهة. يُسقِط
`remit_out_destinations` (لقطة الوجهة) أولاً — يعتمد على `beneficiaries`
و`journal_entries` كليهما — ثم قيد المفتاح الأجنبي/العمود على
`journal_entries.beneficiary_id`، ثم `beneficiaries` نفسه أخيراً — ترتيب
إلزامي بسبب الاعتماديات (لا يمكن إسقاط `beneficiaries` وهي لا تزال
مُشارة إليها من `journal_entries`).

Revision ID: b10a8a234bab
Revises: 220e41749c52
Create Date: 2026-09-22 03:37:14.697547

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b10a8a234bab'
down_revision: Union[str, None] = '220e41749c52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ترتيب إلزامي حسب الاعتماديات — انظر docstring أعلى الملف.
    op.drop_table('remit_out_destinations')
    op.drop_constraint('journal_entries_beneficiary_id_fkey', 'journal_entries', type_='foreignkey')
    op.drop_column('journal_entries', 'beneficiary_id')
    op.drop_table('beneficiaries')


def downgrade() -> None:
    # عكس ترتيب upgrade() بالضبط — beneficiaries أولاً (لا شيء بعد يشير إليها).
    op.create_table('beneficiaries',
    sa.Column('id', sa.BIGINT(), server_default=sa.text("nextval('beneficiaries_id_seq'::regclass)"), autoincrement=True, nullable=False),
    sa.Column('client_id', sa.BIGINT(), autoincrement=False, nullable=False),
    sa.Column('code', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('name', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('account_number', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('bank_name', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('currency_code', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('purpose', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name='beneficiaries_client_id_fkey'),
    sa.ForeignKeyConstraint(['currency_code'], ['currencies.code'], name='beneficiaries_currency_code_fkey'),
    sa.PrimaryKeyConstraint('id', name='beneficiaries_pkey'),
    postgresql_ignore_search_path=False
    )
    op.add_column('journal_entries', sa.Column('beneficiary_id', sa.BIGINT(), autoincrement=False, nullable=True))
    op.create_foreign_key('journal_entries_beneficiary_id_fkey', 'journal_entries', 'beneficiaries', ['beneficiary_id'], ['id'])
    op.create_table('remit_out_destinations',
    sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
    sa.Column('entry_id', sa.BIGINT(), autoincrement=False, nullable=False),
    sa.Column('beneficiary_id', sa.BIGINT(), autoincrement=False, nullable=False),
    sa.Column('beneficiary_name_snapshot', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('account_number_snapshot', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('bank_name_snapshot', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('currency_code', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['beneficiary_id'], ['beneficiaries.id'], name='remit_out_destinations_beneficiary_id_fkey'),
    sa.ForeignKeyConstraint(['currency_code'], ['currencies.code'], name='remit_out_destinations_currency_code_fkey'),
    sa.ForeignKeyConstraint(['entry_id'], ['journal_entries.id'], name='remit_out_destinations_entry_id_fkey'),
    sa.PrimaryKeyConstraint('id', name='remit_out_destinations_pkey'),
    sa.UniqueConstraint('entry_id', name='remit_out_destinations_entry_id_key', postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
