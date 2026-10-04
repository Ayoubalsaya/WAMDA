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
from app.models.enums import AccountType, EntryStatus, LotStatus, OperationType, SwiftStatus

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
    commission_problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.balance_diffs or self.swift_problems or self.lot_problems or self.commission_problems)


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
    """§٢-٨: remaining_qty = original_qty − **صافي** الاستهلاك (الأصلية − العكسية)، مع فحوص بنيوية على
    الصفوف العكسية (٢٠٢٦-١٠-٠٢: الفحص القديم يجمع كل الصفوف فلا يكشف استهلاكاً بقي حيّاً بعد عكس قيده —
    مخزون يضيع بصمت — لأن عكس القيد لم يكن يلمس الصفوف أصلاً).

    ١) remaining_qty = original_qty − صافي الاستهلاك.
    ٢) **كل استهلاك قيده REVERSED له صف عكسي** (وإلا فهذا بالذات الخسارة الصامتة).
    ٣) كل صف عكسي يطابق أصله: نفس الدفعة ونفس الكمية، وقيده هو القيد العاكس لقيد الأصل.
    ٤) الحالة: remaining=0 ⇒ CLOSED؛ وCLOSED برصيد > 0 لا يصحّ إلا لدفعة قيدُها المُنشئ مُلغى.
    """
    problems: list[str] = []
    status_of = dict(db.execute(select(JournalEntry.id, JournalEntry.status)).all())
    reversed_by = dict(db.execute(select(JournalEntry.id, JournalEntry.reversed_by_entry_id)).all())
    all_rows = db.execute(select(LotConsumption)).scalars().all()
    by_id = {c.id: c for c in all_rows}
    reversed_ids = {c.reverses_consumption_id for c in all_rows if c.reverses_consumption_id is not None}
    by_lot: dict[int, list[LotConsumption]] = {}
    for c in all_rows:
        by_lot.setdefault(c.lot_id, []).append(c)

    for lot in db.execute(select(CurrencyLot)).scalars():
        rows = by_lot.get(lot.id, [])
        gross = sum((c.qty for c in rows if c.reverses_consumption_id is None), Decimal("0"))
        undone = sum((c.qty for c in rows if c.reverses_consumption_id is not None), Decimal("0"))
        expected_remaining = lot.original_qty - (gross - undone)
        if expected_remaining != lot.remaining_qty:
            problems.append(
                f"currency_lots.lot_no={lot.lot_no}: remaining_qty={lot.remaining_qty} "
                f"لا يطابق original_qty-net_consumed={expected_remaining}"
            )
        for c in rows:
            if c.reverses_consumption_id is None:
                if status_of.get(c.entry_id) == EntryStatus.REVERSED and c.id not in reversed_ids:
                    problems.append(
                        f"currency_lots.lot_no={lot.lot_no}: استهلاك id={c.id} (qty={c.qty}) قيده {c.entry_id} مُلغى "
                        f"لكن لا صف عكسي له — الكمية ضائعة من المخزون"
                    )
            else:
                orig = by_id.get(c.reverses_consumption_id)
                if orig is None or orig.lot_id != c.lot_id or orig.qty != c.qty:
                    problems.append(f"currency_lots.lot_no={lot.lot_no}: صف عكسي id={c.id} لا يطابق أصله (دفعة/كمية)")
                elif reversed_by.get(orig.entry_id) != c.entry_id:
                    problems.append(f"currency_lots.lot_no={lot.lot_no}: صف عكسي id={c.id} ليس تابعاً للقيد العاكس لقيد أصله")
        if lot.remaining_qty == 0 and lot.status != LotStatus.CLOSED:
            problems.append(f"currency_lots.lot_no={lot.lot_no}: remaining_qty=0 لكن الحالة {lot.status} لا CLOSED")
        if lot.remaining_qty > 0 and lot.status == LotStatus.CLOSED and status_of.get(lot.source_entry_id) != EntryStatus.REVERSED:
            problems.append(
                f"currency_lots.lot_no={lot.lot_no}: الحالة CLOSED وفيها رصيد {lot.remaining_qty} بينما قيدها المُنشئ غير مُلغى"
            )
    return problems


def verify_commission_consistency(db: Session) -> list[str]:
    """عمولة الصرافة (٢٠٢٦-١٠-٠٤): أعمدة القيد (المبلغ · العملة · الاتجاه) تطابق أسطر العمولة الفعلية (4110/5410 بفروعها).
    يُفحص كل قيد EXCHANGE وLOCAL_MOVE أصلي (قيود العكس تعكس الأسطر ولا تحمل أعمدة): IN ⇒ دائن فرع 4110 بعملة العمولة بالمبلغ نفسه؛
    OUT ⇒ مدين فرع 5410؛ ولا أسطر عمولة بلا أعمدة، ولا أعمدة بلا أسطر، ولا اتجاهان معاً."""
    problems: list[str] = []
    parents = {a.code: a.id for a in db.execute(select(Account).where(Account.code.in_(("4110", "5410")))).scalars()}
    if len(parents) < 2:
        return problems
    rev_ids = {a.id for a in db.execute(select(Account).where(Account.parent_id == parents["4110"])).scalars()}
    cost_ids = {a.id for a in db.execute(select(Account).where(Account.parent_id == parents["5410"])).scalars()}
    entries = db.execute(
        select(JournalEntry).where(
            JournalEntry.operation_type.in_((OperationType.EXCHANGE, OperationType.LOCAL_MOVE)), JournalEntry.reverses_entry_id.is_(None))
    ).scalars().all()
    lines_by_entry: dict[int, list[JournalLine]] = {}
    for ln in db.execute(
        select(JournalLine).where(JournalLine.account_id.in_(rev_ids | cost_ids), JournalLine.entry_id.in_([e.id for e in entries] or [-1]))
    ).scalars():
        lines_by_entry.setdefault(ln.entry_id, []).append(ln)
    for e in entries:
        ls = lines_by_entry.get(e.id, [])
        income = [(ln.currency_code, ln.credit - ln.debit) for ln in ls if ln.account_id in rev_ids]
        expense = [(ln.currency_code, ln.debit - ln.credit) for ln in ls if ln.account_id in cost_ids]
        has_cols = e.commission_amount is not None
        if not has_cols:
            if ls:
                problems.append(f"journal_entries.entry_no={e.entry_no}: أسطر عمولة (4110/5410) بلا أعمدة عمولة على القيد")
            continue
        if income and expense:
            problems.append(f"journal_entries.entry_no={e.entry_no}: عمولة بالاتجاهين معاً (إيراد ومصروف)")
            continue
        actual = income if e.commission_direction == "IN" else expense
        other = expense if e.commission_direction == "IN" else income
        total = sum((a for _, a in actual), Decimal("0"))
        ccys = {c for c, _ in actual}
        if other or ccys != {e.commission_currency} or total != e.commission_amount:
            problems.append(
                f"journal_entries.entry_no={e.entry_no}: أعمدة العمولة ({e.commission_direction} {e.commission_amount} {e.commission_currency}) "
                f"لا تطابق أسطرها الفعلية ({'IN' if e.commission_direction == 'IN' else 'OUT'}={total} {sorted(ccys)}"
                f"{'، واتجاه معاكس موجود' if other else ''})"
            )
    return problems


def verify(db: Session) -> VerifyReport:
    """لا يكتب شيئاً — تقرير فقط (`--verify`)."""
    true_balances = compute_true_balances(db)
    return VerifyReport(
        balance_diffs=_diff_against_cache(db, true_balances),
        swift_problems=verify_swift_consistency(db),
        lot_problems=verify_lots_consistency(db),
        commission_problems=verify_commission_consistency(db),
    )


def rebuild(db: Session) -> VerifyReport:
    """يعيد بناء account_balances بالكامل من journal_lines (بلا --verify)."""
    true_balances = compute_true_balances(db)
    report = VerifyReport(
        balance_diffs=_diff_against_cache(db, true_balances),
        swift_problems=verify_swift_consistency(db),
        lot_problems=verify_lots_consistency(db),
        commission_problems=verify_commission_consistency(db),
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
