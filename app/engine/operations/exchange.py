"""EXCHANGE — تحويل بين عملتين بسعرين. §٤ رقم ٣ · الدولار إلزامي في أحد الطرفين.

نمطان بشكل قيد مختلف تماماً (كلاهما في §٢-٣ / §٢-٨ من الوثيقة):

  · `execute_via_rates`  — الحالة العامة (مثال §٢-٣: LYD⇄USD): سعرا التكلفة
    والعميل كلاهما يُطبَّقان على **نفس المبلغ الخام** (عملة "من")، فينتج
    رقمان مختلفان **بعملة "إلى"** — الفرق بينهما هو الربح/الخسارة، ويُقيَّد
    على ضلع "إلى". ضلع "من" مرور نظيف بلا فارق (نفس المبلغ مديناً ودائناً).

  · `execute_via_lot`  — رمبي من مخزون السويفت (مثال §٢-٨-ج، USD→CNY فقط):
    كمية الرمبي المُسلَّمة = تحويل العميل للمبلغ الخام (نظيفة، بلا فارق).
    التكلفة **لا تُدخَل يدوياً** — تُشتق من استهلاك FIFO لتلك الكمية بالذات
    من الدفعات المفتوحة، فيظهر الفارق على ضلع الدولار (عملة "من") بدلاً
    من "إلى"، لأن الدفعة تجمّد سعر تكلفتها لحظة الفتح لا لحظة البيع.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clearing, clock, fx, lots_fifo, posting, profit
from app.engine.rounding import RoundingKind, round_amount
from app.models import Client, JournalEntry
from app.engine.profit import NegativeMarginReasonRequiredError
from app.models.enums import AccountForm, AccountType, OperationType

__all__ = ["InvalidCommissionError", "NegativeMarginReasonRequiredError", "execute_via_rates", "execute_via_lot"]


class InvalidCommissionError(Exception):
    """عمولة الصرافة غير صالحة: حساب بعملة مختلفة، أو حساب ليس للشركة/العميل المناسب، أو بيانات ناقصة."""


_COMPANY_COMMISSION_FORMS = (AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT)


def _add_commission(
    db: Session, draft, *, is_treasury: bool, client: Optional[Client], direction: str, currency_code: str, amount: Decimal,
    account_code: Optional[str], location_code: Optional[str],
) -> None:
    """عمولة الصرافة (٢٠٢٦-١٠-٠٤): زوج أسطر متوازن **بعملتها هي** (لا تحويل لعملة أساس) مستقل عن عملتي الصرف.
    نقبضها (IN): مدين الحساب المختار ← دائن 4110 بفرع عملتها. ندفعها (OUT): مدين 5410 بفرع عملتها ← دائن الحساب المختار.
    الحساب المختار: حساب شركة (صندوق/بنك/مراسل) بعملة العمولة؛ ونطاق العميل يقبل أيضاً حساب العميل نفسه (عملة العمولة × الموقع)."""
    if direction not in ("IN", "OUT"):
        raise InvalidCommissionError("اتجاه العمولة: نقبضها أو ندفعها")
    if amount <= 0:
        raise InvalidCommissionError("مبلغ العمولة يجب أن يكون أكبر من صفر")
    ccy = accounts_repo.get_currency(db, currency_code)
    if account_code:
        account = accounts_repo.get_account_by_code(db, account_code)
        if account.client_id is not None or account.type != AccountType.ASSET or account.form not in _COMPANY_COMMISSION_FORMS:
            raise InvalidCommissionError(f"الحساب {account_code} ليس حساب شركة (صندوق أو بنك أو مراسل) للعمولة")
    elif is_treasury:
        raise InvalidCommissionError("عمولة صرافة الخزينة تتطلب حساب شركة")
    else:
        if not location_code:
            raise InvalidCommissionError("اختر حساب العمولة: موقع حساب العميل أو حساب شركة")
        account = accounts_repo.get_or_create_client_account(db, client=client, currency_code=currency_code, location_code=location_code)
    if account.currency_code != currency_code:
        raise InvalidCommissionError(f"حساب العمولة بعملة {account.currency_code} لا {currency_code} — العمولة بعملتها فقط")
    amount = round_amount(amount, ccy.decimals, RoundingKind.INTERNAL)
    if amount <= 0:
        raise InvalidCommissionError("مبلغ العمولة يُقرَّب إلى صفر بخانات هذه العملة")
    revenue = accounts_repo.get_currency_subaccount(db, "4110", currency_code)
    cost = accounts_repo.get_currency_subaccount(db, "5410", currency_code)
    if direction == "IN":
        draft.add(account_id=account.id, currency_code=currency_code, debit=amount)
        draft.add(account_id=revenue.id, currency_code=currency_code, credit=amount)
    else:
        draft.add(account_id=cost.id, currency_code=currency_code, debit=amount)
        draft.add(account_id=account.id, currency_code=currency_code, credit=amount)
    draft.entry.commission_amount = amount
    draft.entry.commission_currency = currency_code
    draft.entry.commission_direction = direction


def execute_via_rates(
    db: Session,
    *,
    from_currency: str,
    to_currency: str,
    amount: Decimal,
    client_rate: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
    backdate_reason: Optional[str] = None,
    idempotency_key: str,
    cost_rate: Optional[Decimal] = None,
    client: Optional[Client] = None,
    from_location_code: Optional[str] = None,
    to_location_code: Optional[str] = None,
    source_account_code: Optional[str] = None,
    destination_account_code: Optional[str] = None,
    description: Optional[str] = None,
    negative_margin_reason: Optional[str] = None,
    chain_ref: Optional[str] = None,
    chain_seq: Optional[int] = None,
    chain_total: Optional[int] = None,
    commission_direction: Optional[str] = None,
    commission_currency: Optional[str] = None,
    commission_amount: Optional[Decimal] = None,
    commission_account_code: Optional[str] = None,
    commission_location_code: Optional[str] = None,
) -> JournalEntry:
    """نطاقان (٢٠٢٦-٠٩-٢٤، طلب مالك — لا نوع عملية ثالث عشر): **عميل**
    (`client`+المواقع، الأصل) أو **خزينة** (`source_account_code`+
    `destination_account_code`، لا عميل إطلاقاً — تحويل بين حسابي شركة عبر
    مراسل/صندوق طرف ثالث، مثال §١-٥). المستدعي يمرِّر أحدهما حصراً —
    التحقق من الحصرية عند طبقة HTTP (`ExchangeRatesRequest`)، لا هنا.

    **نطاق العميل — سعران**: `cost_rate` إلزامي، والربح = تكلفة−عميل (فارق
    يُبقيه الوسيط) على ضلع "إلى"، يغذّي `profit.account_and_side`.

    **نطاق الخزينة — سعر واحد** (٢٠٢٦-١٠-٠٢، طلب مالك): `client_rate` هو
    السعر المنفَّذ فعلاً، و`cost_rate` غير مسموح. لا ربح ولا خسارة في
    العملية نفسها (لا سطر 4120/5120، `profit_amount` فارغ) — كل عملة
    تتوازن داخل نفسها عبر مقاصتها `1900.x` بالمبلغ نفسه مديناً ودائناً.

    القطبية معكوسة بين النطاقين لأن حساب العميل `LIABILITY` وحساب
    الخزينة `ASSET` (مدين يُنقِص أحدهما ويزيد الآخر): في نطاق العميل
    `client_from` مدين/`client_to` دائن؛ في نطاق الخزينة `source` دائن
    (يفرغ) و`destination` مدين (يمتلئ) — ومعهما حسابا المقاصة `1900.x`
    بنفس الانعكاس.
    """
    is_treasury = source_account_code is not None
    if (commission_amount is None) != (commission_direction is None) or (commission_amount is None) != (commission_currency is None):
        raise InvalidCommissionError("العمولة تتطلب الاتجاه والعملة والمبلغ معاً")
    if is_treasury and cost_rate is not None:
        raise ValueError("صرافة الخزينة بسعر واحد — لا cost_rate")
    if not is_treasury and cost_rate is None:
        raise ValueError("صرافة العميل تتطلب cost_rate")
    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        fx.assert_pivot_pair(from_currency, to_currency, pivot.code)
        to_ccy_row = accounts_repo.get_currency(db, to_currency)

        to_amount_client = round_amount(
            fx.convert(amount, client_rate, from_currency=from_currency, to_currency=to_currency, pivot_code=pivot.code),
            to_ccy_row.decimals,
            RoundingKind.GIVEN_TO_CLIENT,
        )
        fx.assert_plausible_amount(
            fx.convert(amount, client_rate, from_currency=from_currency, to_currency=to_currency, pivot_code=pivot.code),
            to_amount_client, to_currency,
        )
        if is_treasury:
            to_amount_cost = to_amount_client
            diff = Decimal("0")
        else:
            to_amount_cost = round_amount(
                fx.convert(amount, cost_rate, from_currency=from_currency, to_currency=to_currency, pivot_code=pivot.code),
                to_ccy_row.decimals,
                RoundingKind.INTERNAL,
            )
            diff = to_amount_cost - to_amount_client
            if diff < 0 and not negative_margin_reason:
                raise NegativeMarginReasonRequiredError("هامش سالب — سبب مكتوب إلزامي قبل الترحيل")

        clearing_from = clearing.clearing_account(db, from_currency)
        clearing_to = clearing.clearing_account(db, to_currency)

        if is_treasury:
            from_account = accounts_repo.get_account_by_code(db, source_account_code)
            to_account = accounts_repo.get_account_by_code(db, destination_account_code)
            entry_client_id = None
        else:
            from_account = accounts_repo.get_or_create_client_account(
                db, client=client, currency_code=from_currency, location_code=from_location_code
            )
            to_account = accounts_repo.get_or_create_client_account(
                db, client=client, currency_code=to_currency, location_code=to_location_code
            )
            entry_client_id = client.id

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.EXCHANGE,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            client_id=entry_client_id,
            from_currency=from_currency,
            to_currency=to_currency,
            cost_rate=cost_rate,
            client_rate=client_rate,
            description=description or f"صرافة {from_currency} → {to_currency}",
            negative_margin_reason=negative_margin_reason,
            chain_ref=chain_ref,
            chain_seq=chain_seq,
            chain_total=chain_total,
        )
        if is_treasury:
            draft.add(account_id=from_account.id, currency_code=from_currency, credit=amount)
            draft.add(account_id=clearing_from.id, currency_code=from_currency, debit=amount)
            draft.add(account_id=clearing_to.id, currency_code=to_currency, credit=to_amount_client)
            draft.add(account_id=to_account.id, currency_code=to_currency, debit=to_amount_client)
        else:
            draft.add(account_id=from_account.id, currency_code=from_currency, debit=amount)
            draft.add(account_id=clearing_from.id, currency_code=from_currency, credit=amount)
            draft.add(account_id=clearing_to.id, currency_code=to_currency, debit=to_amount_cost)
            draft.add(account_id=to_account.id, currency_code=to_currency, credit=to_amount_client)

        if not is_treasury:
            pl_account, pl_amounts = profit.account_and_side(db, diff=diff, currency_code=to_currency)
            if pl_account is not None:
                draft.add(account_id=pl_account.id, currency_code=to_currency, **pl_amounts)
            draft.entry.profit_amount = diff
            draft.entry.profit_currency = to_currency
        if commission_amount is not None:
            _add_commission(
                db, draft, is_treasury=is_treasury, client=client, direction=commission_direction, currency_code=commission_currency,
                amount=commission_amount, account_code=commission_account_code, location_code=commission_location_code,
            )
        return posting.post_entry(db, draft, posted_by=created_by, now=now)

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "EXCHANGE_VIA_RATES",
            "commission": [commission_direction, commission_currency, commission_amount, commission_account_code, commission_location_code],
            "client_id": client.id if client else None,
            "source_account_code": source_account_code,
            "destination_account_code": destination_account_code,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "amount": amount,
            "cost_rate": cost_rate,
            "client_rate": client_rate,
        },
        create_fn=_create,
    )


def execute_via_lot(
    db: Session,
    *,
    client: Client,
    from_location_code: str,
    to_location_code: str,
    amount: Decimal,  # بعملة الدولار (from_currency) — ما يدفعه العميل فعلياً
    client_rate: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
    backdate_reason: Optional[str] = None,
    idempotency_key: str,
    description: Optional[str] = None,
) -> JournalEntry:
    """§٢-٨-ج: بيع رمبي من مخزون السويفت — FIFO تلقائي، بلا cost_rate يدوي."""
    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        cny = accounts_repo.get_currency(db, "CNY")
        to_amount_client = round_amount(amount * client_rate, cny.decimals, RoundingKind.GIVEN_TO_CLIENT)

        consumption = lots_fifo.consume(
            db, currency_code="CNY", qty_needed=to_amount_client, cost_decimals=pivot.decimals
        )
        cost_amt = consumption.total_cost
        diff = amount - cost_amt  # موجب = ربح بالدولار

        client_from = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=pivot.code, location_code=from_location_code
        )
        client_to = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code="CNY", location_code=to_location_code
        )
        clearing_from = clearing.clearing_account(db, pivot.code)
        clearing_to = clearing.clearing_account(db, "CNY")

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.EXCHANGE,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            client_id=client.id,
            from_currency=pivot.code,
            to_currency="CNY",
            cost_rate=None,  # مشتق من الدفعة لا يُدخَل يدوياً
            client_rate=client_rate,
            description=description or "صرافة رمبي من مخزون السويفت",
        )
        draft.add(account_id=client_from.id, currency_code=pivot.code, debit=amount)
        draft.add(account_id=clearing_from.id, currency_code=pivot.code, credit=cost_amt)

        pl_account, pl_amounts = profit.account_and_side(db, diff=diff, currency_code=pivot.code)
        if pl_account is not None:
            draft.add(account_id=pl_account.id, currency_code=pivot.code, **pl_amounts)

        draft.add(account_id=clearing_to.id, currency_code="CNY", debit=to_amount_client)
        draft.add(account_id=client_to.id, currency_code="CNY", credit=to_amount_client)

        draft.entry.profit_amount = diff
        draft.entry.profit_currency = pivot.code
        entry = posting.post_entry(db, draft, posted_by=created_by, now=now)

        lots_fifo.apply_consumption(
            db, result=consumption, entry_id=entry.id, client_rate=client_rate, cost_decimals=pivot.decimals, now=now
        )
        return entry

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "EXCHANGE_VIA_LOT",
            "client_id": client.id,
            "amount": amount,
            "client_rate": client_rate,
        },
        create_fn=_create,
    )
