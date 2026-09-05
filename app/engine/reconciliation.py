"""منطق المطابقة المشترك (§٧-٩) — دفترك مقابل كشف المراسل، **الاتجاهان**:

1. سطر في كشفهم بلا قيد عندك — عملية سجّلوها ولم تسجّلها.
2. قيد عندك بلا سطر في كشفهم — عملية سجّلتها ولم ينفّذوها (**أخطر**:
   مالٌ تظنّه خرج ولم يخرج).

يُستخدَم من موجّه المطابقة (`app/routers/reconciliation.py`) لبناء العرض
جنباً إلى جنب، ومن لوحة التحكم (`_compute_alerts`) لعدّ الفروق غير
المسوّاة لكل مراسل — نفس المنطق، مصدر واحد.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import Account, JournalEntry, JournalLine, PartnerStatement, PartnerStatementLine
from app.models.enums import EntryStatus, ReconciliationStatus

MATCH_DATE_TOLERANCE = timedelta(days=3)


@dataclass
class LedgerEntryView:
    entry_id: int
    entry_no: str
    entry_date: date
    operation_type: str
    description: str | None
    amount: Decimal  # صافي أثر القيد على حسابات هذا المراسل (دائن − مدين)
    matched_line_id: int | None


def partner_account_ids(db: OrmSession, partner_id: int) -> list[int]:
    return list(db.execute(select(Account.id).where(Account.partner_id == partner_id)).scalars().all())


def partner_ledger_entries(
    db: OrmSession, *, partner_id: int, period_from: date, period_to: date,
) -> list[LedgerEntryView]:
    """قيود دفترك التي تمسّ أي حساب لهذا المراسل ضمن فترة الكشف (± سماحية)،
    مع بيان أيّ سطر كشف طُوبِق بكلٍّ منها (إن وُجد)."""
    acct_ids = partner_account_ids(db, partner_id)
    if not acct_ids:
        return []
    date_from = period_from - MATCH_DATE_TOLERANCE
    date_to = period_to + MATCH_DATE_TOLERANCE

    rows = db.execute(
        select(JournalEntry, JournalLine)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(
            JournalLine.account_id.in_(acct_ids),
            JournalEntry.status == EntryStatus.POSTED,
            JournalEntry.entry_date >= date_from,
            JournalEntry.entry_date <= date_to,
        )
        .order_by(JournalEntry.entry_date, JournalEntry.id)
    ).all()

    matched_by_entry = {
        line.matched_entry_id: line.id
        for line in db.execute(
            select(PartnerStatementLine).where(PartnerStatementLine.matched_entry_id.isnot(None))
        ).scalars().all()
    }

    net_by_entry: dict[int, Decimal] = {}
    meta: dict[int, JournalEntry] = {}
    for entry, line in rows:
        net_by_entry[entry.id] = net_by_entry.get(entry.id, Decimal("0")) + line.credit - line.debit
        meta[entry.id] = entry

    return [
        LedgerEntryView(
            entry_id=e.id, entry_no=e.entry_no, entry_date=e.entry_date,
            operation_type=e.operation_type.value, description=e.description,
            amount=net_by_entry[e.id], matched_line_id=matched_by_entry.get(e.id),
        )
        for e in sorted(meta.values(), key=lambda x: (x.entry_date, x.id))
    ]


@dataclass
class StatementDiff:
    partner_id: int
    unmatched_statement_lines: int  # سجّلوها ولم تسجّلها
    unmatched_ledger_entries: int   # سجّلتها ولم ينفّذوها (أخطر)

    @property
    def total(self) -> int:
        return self.unmatched_statement_lines + self.unmatched_ledger_entries


def statement_diff(db: OrmSession, statement: PartnerStatement) -> StatementDiff:
    open_lines = db.execute(
        select(PartnerStatementLine).where(
            PartnerStatementLine.statement_id == statement.id,
            PartnerStatementLine.status == ReconciliationStatus.OPEN,
        )
    ).scalars().all()
    entries = partner_ledger_entries(
        db, partner_id=statement.partner_id,
        period_from=statement.period_from, period_to=statement.period_to,
    )
    return StatementDiff(
        partner_id=statement.partner_id,
        unmatched_statement_lines=len(open_lines),
        unmatched_ledger_entries=sum(1 for e in entries if e.matched_line_id is None),
    )
