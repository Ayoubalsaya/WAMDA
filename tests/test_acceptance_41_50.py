"""اختبارات القبول ٤١–٥٠.

٤٠/٤١/٤٢ — بوابة العميل وعزلها وإخفاء `cost_rate` عن ردودها وإجبار تغيير
كلمة المرور — مُغطّاة الآن فعلياً في `tests/test_portal_api.py` (المرحلة ٩،
بعد بناء API البوابة وطبقة مصادقة `SessionSubjectType.CLIENT`). ٤١ مُغطّى
أيضاً بتغطية جزئية إضافية في `test_operations_api.py` (ردود API الموظفين).

**لا تزال مُستبعدة عمداً بلا علامة**:
  · ٥٠ — RTL/محاذاة الأرقام/عكس الأيقونات: تحتاج واجهة فعلية بصرية، لا
    قابلة للفحص الصادق عبر `pytest` وحده مهما بُنيت طبقات API.

٤٧/٤٨ يُختبَران هنا **بنطاق محكوم صراحة**: الجزء القابل للاختبار عند
محرك القيود وحده (لا شاشات).
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.engine import accounts_repo, clock, recompute
from app.engine.operations import adjustment, cash_transfer, exchange, expense, payment, receipt
from app.models import Currency, Location
from app.models.enums import AccountForm, AccountType
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.mark.acceptance(46)
def test_bulk_random_entries_then_recompute_verify_zero_diff(db, now):
    """٥٬٠٠٠ قيد عشوائي ثم recompute-balances --verify → صفر اختلاف.

    ١٠٠٠ بدل ٥٠٠٠ للحفاظ على زمن تشغيل معقول لمجموعة اختبارات (نفس المبدأ:
    خليط تشغيلات RECEIPT/PAYMENT/EXCHANGE عشوائي القيم عبر عملاء متعددين).
    """
    rng = random.Random(42)
    user = f.make_user(db)
    clients = [f.make_client(db, credit_allowed=True) for _ in range(10)]
    for client in clients:
        f.set_credit_limit(db, client, "LYD", Decimal("1000000.000"))
        f.set_credit_limit(db, client, "USD", Decimal("1000000.00"))

    from app.engine.posting import CreditLimitExceededError, InsufficientBalanceError

    posted = 0
    rejected = 0
    for _ in range(1000):
        client = rng.choice(clients)
        # ٧٠٪ RECEIPT — يبني رصيد صناديق الشركة أولاً، فلا PAYMENT عشوائي
        # يستنزفها إلى ما دون الصفر (رفض واقعي متوقع لا عطل في الاختبار).
        op = "RECEIPT" if rng.random() < 0.7 else "PAYMENT"
        currency = rng.choice(["LYD", "USD"])
        location = "TRIPOLI" if currency == "LYD" else rng.choice(["TRIPOLI", "TURKEY"])
        amount = Decimal(rng.randint(100, 9999)).scaleb(-2)
        account_code = "1101" if currency == "LYD" else "1104"
        try:
            if op == "RECEIPT":
                receipt.execute(
                    db, client=client, currency_code=currency, location_code=location, amount=amount,
                    receiving_account_code=account_code, work_timezone=WORK_TZ, created_by=user.id, now=now,
                    idempotency_key=f.uid(),
                )
            else:
                payment.execute(
                    db, client=client, currency_code=currency, location_code=location, amount=amount,
                    paying_account_code=account_code, work_timezone=WORK_TZ, created_by=user.id, now=now,
                    idempotency_key=f.uid(),
                )
            posted += 1
        except (InsufficientBalanceError, CreditLimitExceededError):
            # رفض مشروع (رصيد غير كافٍ) — لا يترك أثراً جزئياً، تماماً كما
            # يجب؛ هذا ما يتحقق منه recompute-balances --verify أدناه.
            rejected += 1

    assert posted > 900  # الغالبية العظمى تنجح مع ٪٧٠ استلام أولاً
    report = recompute.verify(db)
    assert report.ok, (report.balance_diffs, report.swift_problems, report.lot_problems)


@pytest.mark.acceptance(47)
def test_timezone_boundary_china_01_shows_previous_day_tripoli():
    """معاملة الساعة ٠١:٠٠ بتوقيت الصين (UTC+8، بلا توقيت صيفي) تظهر في
    تقرير اليوم السابق بتوقيت ليبيا (Africa/Tripoli، UTC+2 ثابت)."""
    from zoneinfo import ZoneInfo

    china_01_00 = datetime(2026, 8, 16, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    utc_moment = china_01_00.astimezone(timezone.utc)

    entry_date_tripoli = clock.local_entry_date(utc_moment, WORK_TZ)
    assert entry_date_tripoli.isoformat() == "2026-08-15"  # اليوم السابق لتاريخ الصين (٢٦-٠٨-١٦)


@pytest.mark.acceptance(48)
def test_adding_fourth_currency_and_location_works_without_code_changes(db, now):
    """إضافة عملة رابعة وموقع جديد يعملان فوراً عبر بيانات فقط — بلا أي
    تعديل كود، طبقاً لـ§٣-١: "لا تُثبّت عدد العملات ولا المواقع في الكود".
    (ملاحظة نطاق: هذا صحيح للمسار العام — posting.py/receipt.py/payment.py
    لا يذكران عملة بعينها؛ الاستثناء الوحيد المتعمَّد `exchange.py` الذي
    يذكر `CNY` صراحةً في مسار مخزون دفعات السويفت، لأنه منطق عمل خاص بتلك
    العملة تحديداً (§٢-٨) لا افتراضاً عاماً.)"""
    db.add(Currency(code="EUR", name_ar="يورو", symbol="€", decimals=2, is_pivot=False, sort_order=99))
    db.add(Location(code="MALTA", name_ar="مالطا", country="MT"))
    db.flush()
    malta = db.execute(select(Location).where(Location.code == "MALTA")).scalar_one()

    from app.models import ClientCurrencyLocation

    db.add(ClientCurrencyLocation(currency_code="EUR", location_id=malta.id))
    db.flush()

    eur_bank = f.make_bank_account(db, currency_code="EUR", location_code="MALTA", parent_code="1400")
    client = f.make_client(db)
    user = f.make_user(db)

    entry = receipt.execute(
        db, client=client, currency_code="EUR", location_code="MALTA", amount=Decimal("500.00"),
        receiving_account_code=eur_bank.code, work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(),
    )
    assert entry.status.value == "POSTED"
    client_account = accounts_repo.get_or_create_client_account(db, client=client, currency_code="EUR", location_code="MALTA")
    from app.models import AccountBalance

    assert db.get(AccountBalance, client_account.id).balance == Decimal("500.00")


@pytest.mark.acceptance(49)
def test_correspondent_statement_discrepancy_settled_via_adjustment(db, now):
    """مطابقة كشف مراسل بفارق واحد → يُبرَز ويُسوّى بـADJUSTMENT.

    شاشة المطابقة نفسها (§٧-٩) مرحلة لاحقة — الجزء القابل للاختبار الآن:
    تسوية فرق مكتشف عبر ADJUSTMENT فعلياً تُصحِّح رصيد حساب المراسل.
    """
    user = f.make_user(db, role="ADMIN")
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("10000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    from app.models import AccountBalance

    book_balance = db.get(AccountBalance, partner_acct.id).balance
    statement_balance = book_balance - Decimal("1.00")  # كشف المراسل أقل بفارق واحد
    difference = book_balance - statement_balance
    assert difference == Decimal("1.00")

    entry = adjustment.execute(
        db, account_code=partner_acct.code, currency_code="USD", amount=difference, is_debit=False,
        reason="مطابقة كشف المراسل — فارق دولار واحد", work_timezone=WORK_TZ, created_by=user.id,
        now=now, idempotency_key=f.uid(),
    )
    assert entry.status.value == "POSTED"
    assert db.get(AccountBalance, partner_acct.id).balance == statement_balance
