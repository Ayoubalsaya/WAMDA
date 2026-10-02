"""اختبارات القبول ٣١–٤٠.

اختبارات القبول ٣١ (مستفيد إلزامي) · ٣٢ (رقم حساب إلزامي) · ٣٣ (لقطة
الوجهة) **أُلغيت عمداً** — سجل المستفيدين أُلغي بالكامل (قرار مالك
٢٠٢٦-٠٩-٢٢)؛ لا معنى للاحتفاظ بها. راجع `conftest.py`/`test_marker_coverage.py`
لاستثنائها الصريح من فحص التغطية الآلي.

اختبار ٤٠ (عزل البوابة على مستوى الاستعلام) **غير مُغطّى عمداً** هنا —
يتطلب طبقة API/بوابة عميل فعلية (المرحلة ٩) لا وجود لها بعد في محرك
قيود بلا واجهة. تركه بلا علامة `acceptance(40)` صادق: تقرير التغطية
النهائي يجب أن يُظهره ناقصاً لا مُغطّى زوراً.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.engine import accounts_repo, opening, posting
from app.engine.operations import opening_balance
from app.engine.posting import BackdatedEntryRequiresAdminError, OutageWindowRequiredError
from app.models import AccountBalance, OutageWindow
from app.models.enums import ConfidenceLevel, EntryStatus, OpeningSourceType
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.mark.acceptance(34)
def test_opening_balance_high_confidence_contra_is_3100(db, now):
    admin = f.make_user(db, role="ADMIN")
    box = f.make_bank_account(db, currency_code="USD")
    entry = opening_balance.execute(
        db, account_code=box.code, currency_code="USD", amount=Decimal("5000.00"), is_debit=True,
        as_of_date=date(2026, 1, 1), source_type=OpeningSourceType.VERIFIED, confidence=ConfidenceLevel.HIGH,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )
    assert entry.status == EntryStatus.POSTED
    contra = accounts_repo.get_currency_subaccount(db, "3100", "USD")
    from app.models import JournalLine

    lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)).scalars().all()
    assert any(l.account_id == contra.id and l.credit == Decimal("5000.00") for l in lines)
    assert sum(l.debit for l in lines) == sum(l.credit for l in lines)


@pytest.mark.acceptance(35)
def test_opening_balance_low_confidence_contra_is_3900(db, now):
    admin = f.make_user(db, role="ADMIN")
    client = f.make_client(db)
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="LYD", location_code="TRIPOLI")
    entry = opening_balance.execute(
        db, account_code=client_account.code, currency_code="LYD", amount=Decimal("50000.000"), is_debit=True,
        as_of_date=date(2026, 1, 1), source_type=OpeningSourceType.RECONSTRUCTED, confidence=ConfidenceLevel.LOW,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
        source_note="عميل مدين — ثقة منخفضة (مثال §٢-١٠)",
    )
    assert entry.status == EntryStatus.POSTED
    contra = accounts_repo.get_currency_subaccount(db, "3900", "LYD")
    from app.models import JournalLine

    lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)).scalars().all()
    assert any(l.account_id == contra.id and l.credit == Decimal("50000.000") for l in lines)
    assert sum(l.debit for l in lines) == sum(l.credit for l in lines)


@pytest.mark.acceptance(36)
def test_resolving_suspense_difference_moves_out_of_3900(db, now):
    admin = f.make_user(db, role="ADMIN")
    client = f.make_client(db)
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="LYD", location_code="TRIPOLI")

    # ٣٩٠٠/٣١٠٠ حسابان عامان مفردان (ليسا نطاقاً معزولاً لكل اختبار مثل
    # حسابات العميل/البنك العشوائية أعلاه) — يحملان أرصدة حقيقية سابقة من
    # فِكستورات QA دائمة مُلتزَمة عمداً (مثال: فِكستور بوابة WebKit، راجع
    # PROGRESS.md)، فلا يصحّ افتراض أنهما يبدآن من صفر. كل الفحوص أدناه
    # فرق ناتج عن أفعال هذا الاختبار تحديداً، لا قيمة مطلقة.
    suspense = accounts_repo.get_currency_subaccount(db, "3900", "LYD")
    capital = accounts_repo.get_currency_subaccount(db, "3100", "LYD")
    suspense_balance_start = db.get(AccountBalance, suspense.id).balance
    capital_balance_start = db.get(AccountBalance, capital.id).balance

    opening_balance.execute(
        db, account_code=client_account.code, currency_code="LYD", amount=Decimal("1000.000"), is_debit=True,
        as_of_date=date(2026, 1, 1), source_type=OpeningSourceType.RECONSTRUCTED, confidence=ConfidenceLevel.LOW,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )
    suspense_balance_before = db.get(AccountBalance, suspense.id).balance
    assert suspense_balance_before == suspense_balance_start + Decimal("1000.000")

    # قيد تسوية: يُحدَّد مصدر الفرق فعلياً برأس المال — من 3900 إلى 3100.
    # لا وحدة عملية مخصَّصة لهذا في الاثني عشر بعد (الوثيقة تصفه فقط
    # كـ"قيد تسوية")؛ LOCAL_MOVE غير مناسب هنا لأن اتفاقية مدين=الوجهة/
    # دائن=المصدر صحيحة لحسابات الأصول فقط، ومقلوبة لحسابات حقوق الملكية
    # (دائن يزيد لا ينقص) — فيُبنى القيد مباشرة عبر بدائيات posting.
    draft = posting.create_draft_entry(
        db, operation_type="ADJUSTMENT", entry_date=now.date(), created_by=admin.id,
        description="تسوية فرق تأسيسي — تحديد مصدره برأس المال",
    )
    draft.add(account_id=suspense.id, currency_code="LYD", debit=Decimal("1000.000"))
    draft.add(account_id=capital.id, currency_code="LYD", credit=Decimal("1000.000"))
    posting.post_entry(db, draft, posted_by=admin.id, now=now)

    assert db.get(AccountBalance, suspense.id).balance == suspense_balance_start
    assert db.get(AccountBalance, capital.id).balance == capital_balance_start + Decimal("1000.000")


@pytest.mark.acceptance(37)
def test_closing_founding_period_with_nonzero_suspense_requires_acknowledgment(db, now):
    admin = f.make_user(db, role="ADMIN")
    client = f.make_client(db)
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="LYD", location_code="TRIPOLI")
    opening_balance.execute(
        db, account_code=client_account.code, currency_code="LYD", amount=Decimal("500.000"), is_debit=True,
        as_of_date=date(2026, 1, 1), source_type=OpeningSourceType.RECONSTRUCTED, confidence=ConfidenceLevel.LOW,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )
    with pytest.raises(opening.SuspenseBalanceAcknowledgmentRequiredError):
        opening.close_founding_period(db, closed_by=admin.id, now=now)

    founding = opening.close_founding_period(
        db, closed_by=admin.id, now=now, acknowledged_remaining_suspense=True
    )
    assert founding.is_open is False
    assert founding.closed_by == admin.id


@pytest.mark.acceptance(38)
def test_outage_entry_stores_both_operation_time_and_entry_time(db, now):
    user = f.make_user(db, role="ADMIN")
    window = OutageWindow(opened_at=now, opened_by=user.id)
    db.add(window)
    db.flush()

    client = f.make_client(db)
    real_time = now
    entry = f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    # الشحنة أعلاه لا تُفعِّل outage_mode — نبني قيداً موازياً صريحاً بوضع الطوارئ
    cash = accounts_repo.get_account_by_code(db, "1101")
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="LYD", location_code="TRIPOLI")
    draft = posting.create_draft_entry(
        db, operation_type="RECEIPT", entry_date=real_time.date(), created_by=user.id,
        outage_mode=True, real_operation_time=real_time, description="قيد طوارئ — انقطاع خدمة",
        backdate_reason="SYSTEM_OUTAGE",
    )
    draft.add(account_id=cash.id, currency_code="LYD", debit=Decimal("50.000"))
    draft.add(account_id=client_account.id, currency_code="LYD", credit=Decimal("50.000"))
    outage_entry = posting.post_entry(db, draft, posted_by=user.id, now=now)

    assert outage_entry.outage_mode is True
    assert outage_entry.real_operation_time == real_time
    assert outage_entry.created_at is not None  # وقت الإدخال الفعلي (مستقل عن وقت العملية)


@pytest.mark.acceptance(39)
def test_outage_entry_outside_window_rejected_and_accountant_after_close_rejected(db, now):
    user = f.make_user(db)
    client = f.make_client(db)
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="LYD", location_code="TRIPOLI")
    cash = accounts_repo.get_account_by_code(db, "1101")

    # لا نافذة طوارئ معلنة إطلاقاً في هذه المعاملة
    with pytest.raises(OutageWindowRequiredError):
        posting.create_draft_entry(
            db, operation_type="RECEIPT", entry_date=now.date(), created_by=user.id,
            outage_mode=True, real_operation_time=now,
        )

    # من محاسب بعد إقفال الفترة — أيضاً مرفوض (نفس ضوابط القيد بأثر رجعي، §٥ قاعدة ١٥)
    from app.models import FoundingPeriod, Period

    founding = db.get(FoundingPeriod, 1)
    founding.is_open = False
    db.add(Period(year=now.year, month=now.month, is_closed=True))
    db.flush()
    accountant = f.make_user(db, role="ACCOUNTANT")
    window = OutageWindow(opened_at=now, opened_by=accountant.id)
    db.add(window)
    db.flush()
    with pytest.raises(BackdatedEntryRequiresAdminError):
        posting.create_draft_entry(
            db, operation_type="RECEIPT", entry_date=now.date(), created_by=accountant.id,
            outage_mode=True, real_operation_time=now,
        )
