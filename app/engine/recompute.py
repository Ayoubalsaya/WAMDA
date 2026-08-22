"""`python -m app.cli recompute-balances --verify` — §٣-٨ / §٩ / اختبار القبول ٤٦.

`journal_entries` + `journal_lines` = المصدر الوحيد. `account_balances` رصيد
مشتق يُعاد بناؤه بالكامل من الصفر — لا تعديل يدوي عليه كوسيلة تصحيح محاسبي.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, AccountBalance, CurrencyLot, JournalEntry, JournalLine, LotConsumption, SwiftMovement
from app.models.enums import AccountType, EntryStatus, LotStatus, SwiftStatus

_CREDIT_NORMAL = (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE)


@dataclass
class BalanceDiff:
    account_id: int
    account_code: str
    cached: Decimal
    computed: Decimal


@dataclass
class VerifyReport:
    balance_diffs: list[BalanceDiff] = field(default_factory=list)
    swift_problems: list[str] = field(default_factory=list)
    lot_problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.balance_diffs or self.swift_problems or self.lot_problems)


def compute_true_balances(db: Session) -> dict[int, Decimal]:
    """يُعيد بناء كل رصيد من journal_lines — لا اعتماد على account_balances.

    يشمل قيود POSTED **و REVERSED** معاً: قيد REVERSED أسطره وقائع تاريخية
    حقيقية أثّرت على الرصيد فعلاً، وإلغاؤها يأتي من أسطر قيد العكس المنفصل
    (وهو نفسه POSTED) لا من استبعاد الأصل. استبعاد REVERSED وحده يكسر
    التناظر بين القيد الأصلي وعكسه وينتج فرقاً وهمياً مقداره أثر نصف العملية.
    DRAFT وحده يُستبعد — أسطره لم تؤثر على أي رصيد فعلي بعد.
    """
    rows = db.execute(
        select(
            JournalLine.account_id,
            Account.type,
            func.sum(JournalLine.debit).label("debit"),
            func.sum(JournalLine.credit).label("credit"),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)))
        .group_by(JournalLine.account_id, Account.type)
    ).all()
    result: dict[int, Decimal] = {}
    for account_id, acc_type, debit, credit in rows:
        sign = 1 if acc_type in _CREDIT_NORMAL else -1
        result[account_id] = sign * ((credit or Decimal("0")) - (debit or Decimal("0")))
    return result


def _diff_against_cache(db: Session, true_balances: dict[int, Decimal]) -> list[BalanceDiff]:
    cached = {row.account_id: row.balance for row in db.execute(select(AccountBalance)).scalars()}
    all_ids = set(true_balances) | set(cached)
    diffs = []
    for acc_id in sorted(all_ids):
        computed = true_balances.get(acc_id, Decimal("0"))
        current = cached.get(acc_id, Decimal("0"))
        if computed != current:
            account = db.get(Account, acc_id)
            diffs.append(
                BalanceDiff(account_id=acc_id, account_code=account.code if account else "?", cached=current, computed=computed)
            )
    return diffs


def verify_swift_consistency(db: Session) -> list[str]:
    """§٣-٥ قاعدة ٦: اتساق swift_movements مع القيود والدفعات."""
    problems: list[str] = []
    for movement in db.execute(select(SwiftMovement)).scalars():
        if movement.status == SwiftStatus.RECEIVED and movement.in_entry_id is None:
            problems.append(f"swift_movements.id={movement.id}: RECEIVED بلا in_entry_id")
        if movement.status == SwiftStatus.RETURNED and movement.return_entry_id is None:
            problems.append(f"swift_movements.id={movement.id}: RETURNED بلا return_entry_id")
        for field_name, entry_id in (
            ("out_entry_id", movement.out_entry_id),
            ("in_entry_id", movement.in_entry_id),
            ("return_entry_id", movement.return_entry_id),
        ):
            if entry_id is None:
                continue
            entry = db.get(JournalEntry, entry_id)
            if entry is None:
                problems.append(f"swift_movements.id={movement.id}: {field_name}={entry_id} غير موجود")
    return problems


def verify_lots_consistency(db: Session) -> list[str]:
    """§٢-٨: remaining_qty = original_qty - مجموع الاستهلاكات، وCLOSED عند الصفر فقط."""
    problems: list[str] = []
    for lot in db.execute(select(CurrencyLot)).scalars():
        consumed = db.execute(
            select(func.coalesce(func.sum(LotConsumption.qty), 0)).where(LotConsumption.lot_id == lot.id)
        ).scalar_one()
        expected_remaining = lot.original_qty - consumed
        if expected_remaining != lot.remaining_qty:
            problems.append(
                f"currency_lots.lot_no={lot.lot_no}: remaining_qty={lot.remaining_qty} "
                f"لا يطابق original_qty-consumed={expected_remaining}"
            )
        if lot.remaining_qty == 0 and lot.status != LotStatus.CLOSED:
            problems.append(f"currency_lots.lot_no={lot.lot_no}: remaining_qty=0 لكن الحالة {lot.status} لا CLOSED")
    return problems


def verify(db: Session) -> VerifyReport:
    """لا يكتب شيئاً — تقرير فقط (`--verify`)."""
    true_balances = compute_true_balances(db)
    return VerifyReport(
        balance_diffs=_diff_against_cache(db, true_balances),
        swift_problems=verify_swift_consistency(db),
        lot_problems=verify_lots_consistency(db),
    )


def rebuild(db: Session) -> VerifyReport:
    """يعيد بناء account_balances بالكامل من journal_lines (بلا --verify)."""
    true_balances = compute_true_balances(db)
    report = VerifyReport(
        balance_diffs=_diff_against_cache(db, true_balances),
        swift_problems=verify_swift_consistency(db),
        lot_problems=verify_lots_consistency(db),
    )
    existing = {row.account_id: row for row in db.execute(select(AccountBalance)).scalars()}
    for acc_id, balance in true_balances.items():
        row = existing.get(acc_id)
        if row is None:
            db.add(AccountBalance(account_id=acc_id, balance=balance))
        else:
            row.balance = balance
    for acc_id, row in existing.items():
        if acc_id not in true_balances:
            row.balance = Decimal("0")
    db.flush()
    return report
