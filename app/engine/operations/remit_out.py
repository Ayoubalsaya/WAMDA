"""REMIT_OUT — إرسال خارجي (لمستلم نهائي) عبر شركة مراسلة. §٤ رقم ٩ · مثال §١-٣-ب.

لا رمبي يُقيَّد في دفاترنا هنا؛ الشركة المراسلة تصرف وترسل من عندها،
فالعملية بأكملها تبقى بعملة الدولار فقط (لا حاجة لمقاصة 1900، ولا دفعة
رمبي — تلك حصراً لمسار بنك الصين المباشر، §٢-٨).

سجل المستفيدين أُلغي (قرار مالك ٢٠٢٦-٠٩-٢٢) — ٩٥٪ من العملاء يعطون
رقم حساب فقط بلا معلومة أخرى، وحقل الملاحظة الحر يكفي لتدوين الوجهة.
لا ربط بمستفيد، لا لقطة وجهة منفصلة — العملة/المبلغ يُدخَلان مباشرة
بدل اشتقاقهما من سجل مستفيد.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, fx, posting, profit
from app.engine.profit import NegativeMarginReasonRequiredError
from app.engine.rounding import RoundingKind, round_amount
from app.models import Client
from app.models.enums import OperationType


def execute(
    db: Session,
    *,
    client: Client,
    from_location_code: str,
    partner_account_code: str,
    currency_code: str,  # عملة المبلغ المُرسَل للمستفيد
    amount: Decimal,
    cost_rate: Decimal,
    client_rate: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
    backdate_reason: Optional[str] = None,
    idempotency_key: str,
    description: Optional[str] = None,
    negative_margin_reason: Optional[str] = None,
    allow_negative: bool = False,
    override_reason: Optional[str] = None,
):
    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)

        def _to_usd(rate: Decimal) -> Decimal:
            # ٢٠٢٦-٠٩-٢٧ (بلاغ مالك — إرسال دولار مباشر كان يعيد HTTP 500):
            # currency_code == pivot.code سيناريو حقيقي شائع (عميل يُسلِّم
            # دولاراً ليُرسَل دولاراً لمستلم في تركيا/الصين) — لا fx.convert
            # هنا لأن assert_pivot_pair يرفض عمداً "عملتان متطابقتان"، وهذا
            # رفض صحيح في EXCHANGE/CASH_TRANSFER (يمنع خطأ استخدام حقيقياً
            # هناك) لكنه هنا حالة عمل صحيحة تماماً: لا حاجة لعبور "الدولار
            # كنقطة تحويل" لأن الدولار هو العملة أصلاً. الضرب المباشر هنا
            # يطابق حرفياً فرع from_currency==pivot_code داخل fx.convert
            # نفسه — rate=1 يعني بلا هامش، أي رقم آخر هامش مقصود، بنفس
            # صيغة الهامش المستخدمة في كل عملية أخرى بالنظام.
            if currency_code == pivot.code:
                return amount * rate
            return fx.convert(amount, rate, from_currency=currency_code, to_currency=pivot.code, pivot_code=pivot.code)

        # المبلغ يُحصَّل من العميل — ROUND_UP (§٢-٥)
        client_amt_usd = round_amount(
            _to_usd(client_rate), pivot.decimals, RoundingKind.COLLECTED_FROM_CLIENT,
        )
        cost_amt_usd = round_amount(
            _to_usd(cost_rate), pivot.decimals, RoundingKind.INTERNAL,
        )
        diff = client_amt_usd - cost_amt_usd  # موجب = ربح (العميل دفع أكثر من التكلفة)
        if diff < 0 and not negative_margin_reason:
            raise NegativeMarginReasonRequiredError("هامش سالب — سبب مكتوب إلزامي قبل الترحيل")

        client_account = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=pivot.code, location_code=from_location_code
        )
        partner_account = accounts_repo.get_account_by_code(db, partner_account_code)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.REMIT_OUT,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            client_id=client.id,
            from_currency=pivot.code,
            cost_rate=cost_rate,
            client_rate=client_rate,
            description=description or "إرسال خارجي",
            negative_margin_reason=negative_margin_reason,
        )
        draft.add(account_id=client_account.id, currency_code=pivot.code, debit=client_amt_usd)
        draft.add(account_id=partner_account.id, currency_code=pivot.code, credit=cost_amt_usd)
        pl_account, pl_amounts = profit.account_and_side(db, diff=diff, currency_code=pivot.code)
        if pl_account is not None:
            draft.add(account_id=pl_account.id, currency_code=pivot.code, **pl_amounts)

        draft.entry.profit_amount = diff
        draft.entry.profit_currency = pivot.code
        return posting.post_entry(
            db, draft, posted_by=created_by, now=now,
            allow_negative=allow_negative, override_reason=override_reason,
        )

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "REMIT_OUT",
            "client_id": client.id,
            "currency_code": currency_code,
            "amount": amount,
            "cost_rate": cost_rate,
            "client_rate": client_rate,
        },
        create_fn=_create,
    )
