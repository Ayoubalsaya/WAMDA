"""محرك الترحيل الأساسي — إنشاء/ترحيل/عكس القيود.

قواعد لا تُخرق (§ توجيهات المرحلة ٢):
  · كل مسار كتابة داخل معاملة قاعدة بيانات واحدة (المستدعي يتحكم بالـ commit).
  · الأقفال بترتيب account_id تصاعدياً دائماً (§٥ قاعدة ١٣).
  · لا استدعاء مباشر لـ datetime.now — `now` يُحقن دائماً.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import idempotency, numbering
from app.models import (
    Account,
    AccountBalance,
    AuditLog,
    Client,
    ClientCreditLimit,
    JournalEntry,
    JournalLine,
)
from app.models.enums import AccountForm, AccountType, EntryStatus, SessionSubjectType

_CREDIT_NORMAL = (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE)


class UnbalancedEntryError(Exception):
    """§٣-٤ قاعدة ١: SUM(debit) = SUM(credit) لكل عملة داخل القيد."""


class InsufficientBalanceError(Exception):
    """§٥ قاعدة ٨: رصيد سالب في صندوق/موقع يمنع الترحيل."""


class CreditLimitExceededError(Exception):
    """§٥ قاعدة ٦/٧: عميل بلا ائتمان أو تجاوز حد الائتمان."""


class OverrideReasonRequiredError(Exception):
    """التجاوز يتطلب سبباً إلزامياً مسجَّلاً (§٥ قاعدة ٨)."""


@dataclass
class LineInput:
    account_id: int
    currency_code: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: Optional[str] = None


@dataclass
class EntryDraft:
    """قيد قيد الإنشاء — تُجمَّع الأسطر هنا قبل post_entry."""

    entry: JournalEntry
    lines: list[LineInput] = field(default_factory=list)

    def add(
        self,
        *,
        account_id: int,
        currency_code: str,
        debit: Decimal = Decimal("0"),
        credit: Decimal = Decimal("0"),
        memo: Optional[str] = None,
    ) -> "EntryDraft":
        self.lines.append(
            LineInput(account_id=account_id, currency_code=currency_code, debit=debit, credit=credit, memo=memo)
        )
        return self


def validate_balance(lines: list[LineInput]) -> None:
    """§٣-٤ قاعدة ١ و٢ — تُفحص أيضاً بمشغّل قاعدة البيانات كخط دفاع أخير."""
    by_currency: dict[str, Decimal] = {}
    for line in lines:
        if line.debit != 0 and line.credit != 0:
            raise UnbalancedEntryError("سطر لا يمكن أن يحمل مديناً ودائناً معاً غير صفر")
        if line.debit < 0 or line.credit < 0:
            raise UnbalancedEntryError("لا قيم سالبة في debit/credit")
        by_currency[line.currency_code] = by_currency.get(line.currency_code, Decimal("0")) + (
            line.debit - line.credit
        )
    unbalanced = {ccy: diff for ccy, diff in by_currency.items() if diff != 0}
    if unbalanced:
        raise UnbalancedEntryError(f"القيد غير متوازن بالعملات: {unbalanced}")


def create_draft_entry(
    db: Session,
    *,
    operation_type,
    entry_date: date,
    created_by: int,
    client_id: Optional[int] = None,
    partner_id: Optional[int] = None,
    beneficiary_id: Optional[int] = None,
    from_currency: Optional[str] = None,
    to_currency: Optional[str] = None,
    cost_rate: Optional[Decimal] = None,
    client_rate: Optional[Decimal] = None,
    description: Optional[str] = None,
    is_backdated: bool = False,
    backdate_reason: Optional[str] = None,
    negative_margin_reason: Optional[str] = None,
    outage_mode: bool = False,
    real_operation_time: Optional[datetime] = None,
    chain_ref: Optional[str] = None,
    chain_seq: Optional[int] = None,
    chain_total: Optional[int] = None,
) -> EntryDraft:
    """ينشئ رأس قيد DRAFT ويخصّص entry_no بلا فجوة — §٥ قاعدة ٩."""
    entry_no = numbering.next_entry_no(db, entry_date.year)
    entry = JournalEntry(
        entry_no=entry_no,
        entry_date=entry_date,
        operation_type=operation_type,
        client_id=client_id,
        partner_id=partner_id,
        beneficiary_id=beneficiary_id,
        from_currency=from_currency,
        to_currency=to_currency,
        cost_rate=cost_rate,
        client_rate=client_rate,
        description=description,
        status=EntryStatus.DRAFT,
        is_backdated=is_backdated,
        backdate_reason=backdate_reason,
        negative_margin_reason=negative_margin_reason,
        outage_mode=outage_mode,
        real_operation_time=real_operation_time,
        chain_ref=chain_ref,
        chain_seq=chain_seq,
        chain_total=chain_total,
        created_by=created_by,
    )
    db.add(entry)
    db.flush()
    return EntryDraft(entry=entry)


def _persist_lines(db: Session, entry: JournalEntry, lines: list[LineInput]) -> list[JournalLine]:
    rows = []
    for i, ln in enumerate(lines, start=1):
        row = JournalLine(
            entry_id=entry.id,
            line_no=i,
            account_id=ln.account_id,
            currency_code=ln.currency_code,
            debit=ln.debit,
            credit=ln.credit,
            memo=ln.memo,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def _log_override(db: Session, entry: JournalEntry, account: Account, action: str, reason: str) -> None:
    db.add(
        AuditLog(
            actor_type=SessionSubjectType.USER,
            actor_id=entry.created_by,
            action=action,
            entity="accounts",
            entity_id=account.id,
            after_json={"reason": reason, "entry_no": entry.entry_no},
        )
    )


def _enforce_balance_policy(
    db: Session,
    *,
    entry: JournalEntry,
    account: Account,
    prospective_balance: Decimal,
    allow_negative: bool,
    override_reason: Optional[str],
) -> None:
    if account.client_id is not None:
        if prospective_balance >= 0:
            return
        client = db.get(Client, account.client_id)
        if not client.credit_allowed:
            # §٥ قاعدة ٦: عميل بلا ائتمان → رفض تام، لا صيغة تجاوز إطلاقاً
            raise CreditLimitExceededError(
                f"العميل {client.code} بلا ائتمان مسموح — لا يمكن أن يصبح رصيده سالباً"
            )
        limit_row = db.get(ClientCreditLimit, (client.id, account.currency_code))
        limit_amount = limit_row.limit_amount if limit_row else Decimal("0")
        if -prospective_balance <= limit_amount:
            return
        if not allow_negative:
            raise CreditLimitExceededError(
                f"تجاوز حد ائتمان العميل {client.code} بعملة {account.currency_code}"
            )
        if not override_reason:
            raise OverrideReasonRequiredError("تجاوز حد الائتمان يتطلب سبباً إلزامياً")
        _log_override(db, entry, account, "CREDIT_LIMIT_OVERRIDE", override_reason)
        return

    # §٢-٣: حسابات المقاصة (1900.x) تعكس "مركزك المكشوف بالتكلفة" لا نقداً
    # فعلياً — تتأرجح موجبة وسالبة حسب اتجاه التدفق بتصميمها، فهي ليست
    # "صندوقاً" بمعنى §٥ قاعدة ٨ وتُستثنى من فحص الرصيد السالب.
    if account.form == AccountForm.CLEARING:
        return

    # حسابات الشركة/الشركاء (أصول) — §٥ قاعدة ٨: لا رصيد سالب في أي صندوق/موقع
    if account.type == AccountType.ASSET and prospective_balance < 0:
        if not allow_negative:
            raise InsufficientBalanceError(f"الحساب {account.code} سيصبح سالباً")
        if not override_reason:
            raise OverrideReasonRequiredError("تجاوز الرصيد السالب يتطلب سبباً إلزامياً")
        _log_override(db, entry, account, "NEGATIVE_BALANCE_OVERRIDE", override_reason)


def post_entry(
    db: Session,
    draft: EntryDraft,
    *,
    posted_by: int,
    now: datetime,
    allow_negative: bool = False,
    override_reason: Optional[str] = None,
) -> JournalEntry:
    """يرحّل قيد DRAFT: يفحص التوازن ثم كفاية الرصيد ثم يحدّث account_balances.

    كل هذا داخل معاملة المستدعي — لا commit هنا.
    """
    entry = draft.entry
    validate_balance(draft.lines)
    _persist_lines(db, entry, draft.lines)

    account_ids = sorted({ln.account_id for ln in draft.lines})
    accounts: dict[int, Account] = {}
    if account_ids:
        # §٥ قاعدة ١٣: الأقفال بترتيب account_id تصاعدياً دائماً
        locked = db.execute(
            select(Account).where(Account.id.in_(account_ids)).order_by(Account.id).with_for_update()
        ).scalars().all()
        accounts = {a.id: a for a in locked}

    deltas: dict[int, Decimal] = {}
    for ln in draft.lines:
        account = accounts[ln.account_id]
        sign = 1 if account.type in _CREDIT_NORMAL else -1
        deltas[ln.account_id] = deltas.get(ln.account_id, Decimal("0")) + sign * (ln.credit - ln.debit)

    balances: dict[int, AccountBalance] = {}
    for acc_id in account_ids:
        bal = db.get(AccountBalance, acc_id)
        if bal is None:
            bal = AccountBalance(account_id=acc_id, balance=Decimal("0"))
            db.add(bal)
            db.flush()
        balances[acc_id] = bal

    for acc_id, delta in deltas.items():
        prospective = balances[acc_id].balance + delta
        _enforce_balance_policy(
            db,
            entry=entry,
            account=accounts[acc_id],
            prospective_balance=prospective,
            allow_negative=allow_negative,
            override_reason=override_reason,
        )

    entry.status = EntryStatus.POSTED
    entry.posted_by = posted_by
    entry.posted_at = now
    db.flush()  # مشغّلات القاعدة: فحص التوازن + عدم تعديل قيد مُرحّل، خط دفاع أخير

    for acc_id, delta in deltas.items():
        balances[acc_id].balance = balances[acc_id].balance + delta
    db.flush()

    return entry


def reverse_entry(
    db: Session,
    original: JournalEntry,
    *,
    reason: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
) -> JournalEntry:
    """§٥ قاعدة ٢: «تعديل» = قيد عكسي + قيد جديد. لا UPDATE/DELETE على قيد مُرحّل."""
    if original.status != EntryStatus.POSTED:
        raise ValueError("لا يمكن عكس قيد غير مُرحّل")
    if not reason:
        raise OverrideReasonRequiredError("عكس القيد يتطلب سبباً إلزامياً")

    original_lines = db.execute(
        select(JournalLine).where(JournalLine.entry_id == original.id).order_by(JournalLine.line_no)
    ).scalars().all()

    draft = create_draft_entry(
        db,
        operation_type=original.operation_type,
        entry_date=entry_date or original.entry_date,
        created_by=created_by,
        client_id=original.client_id,
        partner_id=original.partner_id,
        beneficiary_id=original.beneficiary_id,
        from_currency=original.from_currency,
        to_currency=original.to_currency,
        cost_rate=original.cost_rate,
        client_rate=original.client_rate,
        description=f"عكس {original.entry_no}: {reason}",
    )
    draft.entry.correction_reason = reason
    for line in original_lines:
        draft.add(
            account_id=line.account_id,
            currency_code=line.currency_code,
            debit=line.credit,
            credit=line.debit,
            memo=line.memo,
        )

    reversal = post_entry(db, draft, posted_by=created_by, now=now)
    reversal.reverses_entry_id = original.id
    original.status = EntryStatus.REVERSED
    original.reversed_by_entry_id = reversal.id
    db.flush()
    return reversal


def execute_idempotent(
    db: Session,
    *,
    idempotency_key: str,
    request_payload: dict,
    create_fn: Callable[[], JournalEntry],
) -> JournalEntry:
    """§٦-٤ — غلاف مشترك لكل وحدات operations/: نفس المفتاح بنفس المحتوى
    يُعيد نفس القيد بلا إنشاء جديد؛ بمحتوى مختلف يُرفض (`IdempotencyConflict`).
    """
    result = idempotency.run(
        db, idempotency_key=idempotency_key, request_payload=request_payload, create_fn=create_fn
    )
    return db.get(JournalEntry, result.entry_id)
