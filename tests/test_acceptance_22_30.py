"""اختبارات القبول ٢٢–٣٠."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.engine import accounts_repo, posting
from app.engine.operations import exchange
from app.engine.posting import (
    BackdatedEntryRequiresAdminError,
    CreditLimitExceededError,
    InsufficientBalanceError,
    OverrideReasonRequiredError,
)
from app.engine.profit import NegativeMarginReasonRequiredError
from app.engine.rounding import RoundingKind, round_amount
from app.models import AccountBalance, AuditLog, FoundingPeriod, JournalLine, Period
from app.models.enums import EntryStatus
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.mark.acceptance(22)
def test_rounding_matrix_matches_document_exactly(db, now):
    """§٢-٥: GIVEN_TO_CLIENT=DOWN · COLLECTED_FROM_CLIENT=UP · INTERNAL=HALF_UP.

    لا شاشة/تقرير بعد يستهلك ٥٩٠٠ في أي من العمليات الاثني عشر الحالية —
    "الفرق" الذي تنتجه EXCHANGE/REMIT_OUT هامش اقتصادي حقيقي (سعرا تكلفة
    وعميل مختلفان) لا فرق تقريب، فيُقيَّد في 4120/5120 لا 5900 (§٢-٣، مطابق
    لأمثلة §١-٣ المُتحقَّق منها في الاختبارات ٣/٤/٥/١٢). يُختبَر هنا مباشرة:
    مصفوفة التقريب نفسها بأرقام كسرية في الاتجاهين، و٥٩٠٠ يبقى صفراً في
    عملية عادية بكسور حقيقية.
    """
    # نفس الكسر (10000/5.10=1960.78431...٤) تحت وضعين مختلفين يُنتج رقمين مختلفين
    exact = Decimal("10000") / Decimal("5.10")
    assert round_amount(exact, 2, RoundingKind.GIVEN_TO_CLIENT) == Decimal("1960.78")  # ROUND_DOWN
    assert round_amount(exact, 2, RoundingKind.COLLECTED_FROM_CLIENT) == Decimal("1960.79")  # ROUND_UP
    assert round_amount(exact, 2, RoundingKind.INTERNAL) == Decimal("1960.78")  # HALF_UP (.4843 < .5)

    half_case = Decimal("1960.785")
    assert round_amount(half_case, 2, RoundingKind.INTERNAL) == Decimal("1960.79")  # HALF_UP يرفع عند .5 بالضبط

    # عملية حقيقية بكسور في الاتجاهين (سعرا تكلفة/عميل غير قابلين للقسمة الصحيحة)
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry = exchange.execute_via_rates(
        db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
        to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.17"),
        client_rate=Decimal("5.13"), work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(), negative_margin_reason="سعر السوق لحظة العملية",
    )
    lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)).scalars().all()
    for line in lines:
        # كل مبلغ في القيد مُقرَّب فعلياً لعدد خانات عملته — لا كسور زائدة أبداً
        decimals = 3 if line.currency_code == "LYD" else 2
        quant = Decimal(1).scaleb(-decimals)
        for amount in (line.debit, line.credit):
            assert amount == amount.quantize(quant)

    account_5900 = accounts_repo.get_account_by_code(db, "5900")
    balance_5900 = db.get(AccountBalance, account_5900.id)
    assert balance_5900 is None or balance_5900.balance == Decimal("0")


@pytest.mark.acceptance(23)
def test_single_rounding_function_used_everywhere(db, now):
    """الشاشة/القيد/الإيصال/التقرير تعطي نفس الرقم — لا شاشة/إيصال/تقرير
    بعد (مراحل لاحقة)؛ يُختبَر هنا الشرط الذي يجعل ذلك ممكناً أصلاً: دالة
    تقريب مركزية واحدة، نقية (نفس المدخل ← نفس المخرج دائماً)، ولا مسار
    تقريب آخر في المحرك (لا `.quantize`/`round()` خارج rounding.py).
    """
    import pathlib

    value = Decimal("1234.567891")
    results = {round_amount(value, 2, RoundingKind.INTERNAL) for _ in range(50)}
    assert results == {Decimal("1234.57")}  # نفس الوسائط → نفس الناتج دائماً

    engine_dir = pathlib.Path(__file__).resolve().parents[1] / "app" / "engine"
    offenders = []
    for path in engine_dir.rglob("*.py"):
        if path.name == "rounding.py":
            continue
        text_content = path.read_text(encoding="utf-8")
        if ".quantize(" in text_content or "round(" in text_content:
            offenders.append(str(path))
    assert offenders == [], f"تقريب خارج rounding.py في: {offenders}"


@pytest.mark.acceptance(24)
def test_edit_posted_entry_is_reversal_plus_new_entry(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    original = f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    reversal = posting.reverse_entry(db, original, reason="تصحيح: المبلغ خطأ", created_by=user.id, now=now)
    db.refresh(original)
    assert original.status == EntryStatus.REVERSED
    assert original.reversed_by_entry_id == reversal.id
    assert reversal.reverses_entry_id == original.id

    # "الجديد" الصحيح: قيد استلام آخر بالمبلغ الصحيح
    corrected = f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("9500.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="LYD", location_code="TRIPOLI")
    assert db.get(AccountBalance, client_account.id).balance == Decimal("9500.000")  # الأصلي أُلغي تماماً


@pytest.mark.acceptance(25)
def test_direct_sql_update_on_posted_entry_rejected_by_trigger(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    entry = f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("1000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    line = db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)).scalars().first()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE journal_lines SET debit = debit + 1 WHERE id = :id"), {"id": line.id})
    # المعاملة تصير aborted بعد خطأ SQL مباشر — لا استعلام تالٍ في هذا الاختبار؛
    # fixture db يُلغيها (rollback) في التنظيف كعادته، فلا حاجة لفعل ذلك هنا.


@pytest.mark.acceptance(26)
def test_backdated_entry_after_period_close_admin_only(db, now):
    founding = db.get(FoundingPeriod, 1)
    founding.is_open = False
    db.add(Period(year=now.year, month=now.month, is_closed=True))
    db.flush()

    accountant = f.make_user(db, role="ACCOUNTANT")
    admin = f.make_user(db, role="ADMIN")
    client = f.make_client(db)

    with pytest.raises(BackdatedEntryRequiresAdminError):
        f.fund_client(
            db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
            receiving_account_code="1101", user=accountant, now=now,
            idempotency_key=f.uid(),
        )

    # مدير بلا سبب أيضاً مرفوض (السبب إلزامي)
    with pytest.raises(OverrideReasonRequiredError):
        posting.create_draft_entry(
            db, operation_type="RECEIPT", entry_date=date(now.year, now.month, 10), created_by=admin.id,
        )

    draft = posting.create_draft_entry(
        db, operation_type="RECEIPT", entry_date=date(now.year, now.month, 10), created_by=admin.id,
        backdate_reason="تصحيح بأثر رجعي بموافقة الإدارة",
    )
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="LYD", location_code="TRIPOLI")
    cash = accounts_repo.get_account_by_code(db, "1101")
    draft.add(account_id=cash.id, currency_code="LYD", debit=Decimal("100.000"))
    draft.add(account_id=client_account.id, currency_code="LYD", credit=Decimal("100.000"))
    entry = posting.post_entry(db, draft, posted_by=admin.id, now=now)
    assert entry.status == EntryStatus.POSTED


@pytest.mark.acceptance(27)
def test_negative_margin_requires_reason_and_is_recorded(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    with pytest.raises(NegativeMarginReasonRequiredError):
        exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
            to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
            client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(),
        )
    entry = exchange.execute_via_rates(
        db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
        to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
        client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(), negative_margin_reason="عرض ترويجي محدود",
    )
    assert entry.status == EntryStatus.POSTED
    assert entry.negative_margin_reason == "عرض ترويجي محدود"
    assert entry.profit_amount < 0  # يظهر لاحقاً في "تقرير العمليات الخاسرة" (مرحلة لاحقة)


@pytest.mark.acceptance(28)
def test_negative_balance_override_requires_reason_and_is_audited(db, now):
    """التجاوز نفسه مُفعَّل الآن (اختبار ٢٧/٢٨ ذاته يتطلبه) — تفويض مَن
    يملك حق `allow_negative=True` (مدير حصراً) مؤجَّل صراحةً للمرحلة ٤
    كما اعتُمد في مراجعة المرحلة ٢. هنا: الحاجز يرفض بلا تجاوز، ويتطلب
    سبباً مع التجاوز، ويُسجَّل التجاوز في audit_log (أساس تقرير «تجاوزات
    الرصيد» لاحقاً).
    """
    from app.engine.operations import payment

    client = f.make_client(db, credit_allowed=True)
    f.set_credit_limit(db, client, "USD", Decimal("0.01"))  # حد رمزي — أي تجاوز يمر بمسار override
    user = f.make_user(db)
    account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="USD", location_code="TRIPOLI")

    def _pay(*, allow_negative, reason=None):
        return payment.execute(
            db, client=client, currency_code="USD", location_code="TRIPOLI", amount=Decimal("100.00"),
            paying_account_code="1104", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), allow_negative=allow_negative, override_reason=reason,
        )

    with pytest.raises(CreditLimitExceededError):
        _pay(allow_negative=False)

    with pytest.raises(OverrideReasonRequiredError):
        _pay(allow_negative=True, reason=None)

    entry = _pay(allow_negative=True, reason="تسوية بموافقة الإدارة")
    assert entry.status == EntryStatus.POSTED
    overrides = db.execute(
        select(AuditLog).where(AuditLog.action == "CREDIT_LIMIT_OVERRIDE", AuditLog.entity_id == account.id)
    ).scalars().all()
    assert len(overrides) >= 1


@pytest.mark.acceptance(29)
def test_client_without_credit_any_negative_rejected(db, now):
    from app.engine.operations import payment

    client = f.make_client(db, credit_allowed=False)
    user = f.make_user(db)
    with pytest.raises(CreditLimitExceededError):
        payment.execute(
            db, client=client, currency_code="USD", location_code="TRIPOLI", amount=Decimal("1.00"),
            paying_account_code="1104", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(),
        )


@pytest.mark.acceptance(30)
def test_positive_in_one_location_negative_in_another_rejected_no_netting(db, now):
    """عميل موجب في تركيا وسالب في الصين → مرفوض (المنع على مستوى الموقع
    — لا مقاصة بين المواقع حتى مع credit_allowed=false)."""
    from app.engine.operations import payment

    client = f.make_client(db, credit_allowed=False)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    # موجب فعلاً في تركيا — محاولة سحب من الصين (رصيد صفري هناك) تُرفض رغم فائض تركيا
    with pytest.raises(CreditLimitExceededError):
        payment.execute(
            db, client=client, currency_code="USD", location_code="CHINA", amount=Decimal("1.00"),
            paying_account_code="1104", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(),
        )
