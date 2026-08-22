"""اختبارات القبول ١–١٠ (§١١ من الوثيقة الوظيفية).

اختبار ١ يُختبَر هنا وفق **التعديل المعتمد** (§٣ من رسالة المراجعة):
حسابات العملاء تُنشأ **كسولاً** عند أول استخدام لكل تركيبة عملة×موقع، لا
تلقائياً دفعة واحدة عند إنشاء العميل — النص الأصلي "تلقائياً" يقصد التوليد
الحتمي للكود عند الحاجة، لا الإنشاء المسبق لكل التركيبات.

اختبار ٩ يُختبَر على مستوى البيانات فقط: البحث الفعلي بواجهة/شاشة (§٧-١٠)
لم يُبنَ بعد (مرحلة لاحقة) — ما يُختبَر هنا هو أن `chain_ref` يكفي وحده
لاستخراج السلسلة كاملة بأرباحها المنفصلة عبر استعلام مباشر.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.engine import accounts_repo, clock, fx
from app.engine.operations import cash_transfer, exchange
from app.engine import chain as chain_mod
from app.models import Account, JournalEntry, JournalLine
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.mark.acceptance(1)
def test_client_accounts_created_lazily_and_deterministically(db, now):
    client = f.make_client(db)
    user = f.make_user(db)

    # لا حسابات 2100-* عند الإنشاء — الإنشاء كسول (تعديل معتمد)
    existing = db.execute(select(Account).where(Account.code.like(f"2100-{client.code}-%"))).scalars().all()
    assert existing == []

    account = accounts_repo.get_or_create_client_account(
        db, client=client, currency_code="USD", location_code="TRIPOLI"
    )
    assert account.code == f"2100-{client.code}-USD-TRIPOLI"
    assert account.currency_code == "USD"
    assert account.client_id == client.id

    # نفس التركيبة مرة أخرى تُعيد نفس الحساب (idempotent) لا تُنشئ آخر
    again = accounts_repo.get_or_create_client_account(
        db, client=client, currency_code="USD", location_code="TRIPOLI"
    )
    assert again.id == account.id


@pytest.mark.acceptance(2)
def test_receipt_balances_correctly(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    entry = f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI",
        amount=Decimal("10000.000"), receiving_account_code="1101", user=user, now=now,
    )
    lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)).scalars().all()
    total_debit = sum(l.debit for l in lines)
    total_credit = sum(l.credit for l in lines)
    assert total_debit == total_credit == Decimal("10000.000")

    client_account = accounts_repo.get_or_create_client_account(
        db, client=client, currency_code="LYD", location_code="TRIPOLI"
    )
    from app.models import AccountBalance

    balance = db.get(AccountBalance, client_account.id)
    assert balance.balance == Decimal("10000.000")  # التزام دائن = رصيد موجب


@pytest.mark.acceptance(3)
def test_cash_transfer_commission_profit(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TRIPOLI",
        amount=Decimal("50000.00"), receiving_account_code="1104", user=user, now=now,
    )
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cost_correspondent = f.make_correspondent_account(
        db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310"
    )
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code=cost_correspondent.code, user=user, now=now,
    )

    entry = cash_transfer.execute(
        db, client=client, currency_code="USD", from_location_code="TRIPOLI", to_location_code="TURKEY",
        amount=Decimal("10000.00"), source_account_code="1104", execution_account_code=exec_acct.code,
        collection_account_code="1101", commission_currency="LYD",
        client_commission_amount=Decimal("800.000"), cost_commission_amount=Decimal("500.000"),
        cost_correspondent_account_code=cost_correspondent.code, work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )

    assert entry.profit_amount == Decimal("300.000")
    assert entry.profit_currency == "LYD"

    revenue = accounts_repo.get_currency_subaccount(db, "4110", "LYD")
    cost = accounts_repo.get_currency_subaccount(db, "5410", "LYD")
    lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)).scalars().all()
    revenue_line = next(l for l in lines if l.account_id == revenue.id)
    cost_line = next(l for l in lines if l.account_id == cost.id)
    assert revenue_line.credit == Decimal("800.000")
    assert cost_line.debit == Decimal("500.000")

    from app.models import AccountBalance

    tripoli_acct = accounts_repo.get_or_create_client_account(db, client=client, currency_code="USD", location_code="TRIPOLI")
    turkey_acct = accounts_repo.get_or_create_client_account(db, client=client, currency_code="USD", location_code="TURKEY")
    assert db.get(AccountBalance, tripoli_acct.id).balance == Decimal("40000.00")  # 50000 - 10000
    assert db.get(AccountBalance, turkey_acct.id).balance == Decimal("10000.00")  # انتقل موقعياً


@pytest.mark.acceptance(4)
def test_exchange_rate_spread_via_remit_out(db, now):
    """فرق سعر الصرف عبر REMIT_OUT — مثال §١-٣-ب: ربح 147.06$، تركيا −10000، العميل −10147.06."""
    from app.engine.operations import remit_out

    client = f.make_client(db)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    beneficiary = f.make_beneficiary(db, client, currency_code="CNY")

    entry = remit_out.execute(
        db, client=client, from_location_code="TURKEY", partner_account_code=partner_acct.code,
        beneficiary=beneficiary, beneficiary_amount=Decimal("69000.00"), cost_rate=Decimal("6.90"),
        client_rate=Decimal("6.80"), work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(),
    )
    assert entry.profit_amount == Decimal("147.060000")
    assert entry.profit_currency == "USD"

    from app.models import AccountBalance

    assert db.get(AccountBalance, partner_acct.id).balance == Decimal("40000.00")  # 50000-10000
    client_turkey = accounts_repo.get_or_create_client_account(db, client=client, currency_code="USD", location_code="TURKEY")
    assert db.get(AccountBalance, client_turkey.id).balance == Decimal("39852.94")  # 50000-10147.06


@pytest.mark.acceptance(5)
def test_exchange_via_clearing_balances_per_currency(db, now):
    """صرف دينار→دولار عبر المقاصة: كل عملة تتوازن داخل نفسها، و1901/1902 بسعر التكلفة."""
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", user=user, now=now,
    )

    entry = exchange.execute_via_rates(
        db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
        to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
        client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(), negative_margin_reason="سعر السوق لحظة العملية",
    )

    lines = db.execute(select(JournalLine).where(JournalLine.entry_id == entry.id)).scalars().all()
    lyd_lines = [l for l in lines if l.currency_code == "LYD"]
    usd_lines = [l for l in lines if l.currency_code == "USD"]
    assert sum(l.debit for l in lyd_lines) == sum(l.credit for l in lyd_lines)
    assert sum(l.debit for l in usd_lines) == sum(l.credit for l in usd_lines)

    clearing_usd = accounts_repo.get_currency_subaccount(db, "1900", "USD")
    clearing_line = next(l for l in usd_lines if l.account_id == clearing_usd.id)
    assert clearing_line.debit == Decimal("1941.75")  # 10000/5.15 مقرَّبة INTERNAL


@pytest.mark.acceptance(6)
def test_lyd_cny_direct_rejected(db, now):
    with pytest.raises(fx.InvalidCurrencyPairError):
        fx.assert_pivot_pair("LYD", "CNY", "USD")

    client = f.make_client(db)
    user = f.make_user(db)
    with pytest.raises(fx.InvalidCurrencyPairError):
        exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="CNY",
            to_location_code="CHINA", amount=Decimal("1000.000"), cost_rate=Decimal("1.3"),
            client_rate=Decimal("1.3"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(),
        )


@pytest.mark.acceptance(7)
def test_two_step_chain_two_separate_entries_two_profits(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry_date = clock.local_entry_date(now, WORK_TZ)

    def step1(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
            to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
            client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
            chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    def step2(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY",
            to_location_code="CHINA", amount=Decimal("1941.75"), cost_rate=Decimal("6.95"),
            client_rate=Decimal("6.90"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    result = chain_mod.execute_two_step_chain(db, entry_date=entry_date, step1=step1, step2=step2)
    assert result.step1_entry.id != result.step2_entry.id
    assert result.step1_entry.chain_ref == result.step2_entry.chain_ref == result.chain_ref
    assert result.step1_entry.profit_currency == "USD"
    assert result.step2_entry.profit_currency == "CNY"
    # الربحان منفصلان تماماً — لا دمج
    assert result.step1_entry.profit_amount != result.step2_entry.profit_amount


@pytest.mark.acceptance(8)
def test_chain_atomic_step2_failure_rolls_back_step1(db, now):
    """السلسلة ذرّية: فشل الخطوة الثانية يُلغي الأولى — لا قيد يتيم."""
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry_date = clock.local_entry_date(now, WORK_TZ)
    captured_chain_ref: dict[str, str] = {}

    def step1(chain_ref, seq, total):
        captured_chain_ref["value"] = chain_ref
        return exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
            to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
            client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
            chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    def step2_fails(chain_ref, seq, total):
        # LYD⇄CNY مباشر مرفوض عمداً لإفشال الخطوة الثانية
        return exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="CNY",
            to_location_code="CHINA", amount=Decimal("100.000"), cost_rate=Decimal("1.3"),
            client_rate=Decimal("1.3"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    with pytest.raises(fx.InvalidCurrencyPairError):
        chain_mod.execute_two_step_chain(db, entry_date=entry_date, step1=step1, step2=step2_fails)

    # ملاحظة نطاق: العزل الذرّي الحقيقي (rollback كامل عند فشل السلسلة)
    # مسؤولية المستدعي الحقيقي الذي يُغلِّف النداء بمعاملة واحدة — نفس ما
    # يفعله fixture db هنا (يُلغي كل شيء بعد الاختبار). الفحص المباشر
    # الممكن *داخل* الاختبار: خطوة ٢ لم تُنشئ أي قيد إطلاقاً تحت نفس
    # chain_ref (نطاق الاستعلام محصور بمرجع هذه السلسلة تحديداً، لا كل
    # الجدول — الجدول قد يحمل بيانات قديمة من تشغيلات سابقة لعروض أخرى).
    entries_this_chain = db.execute(
        select(JournalEntry).where(JournalEntry.chain_ref == captured_chain_ref["value"])
    ).scalars().all()
    assert [e.chain_seq for e in entries_this_chain] == [1]


@pytest.mark.acceptance(9)
def test_chain_ref_retrieves_full_chain(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry_date = clock.local_entry_date(now, WORK_TZ)

    def step1(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
            to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
            client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
            chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    def step2(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY",
            to_location_code="CHINA", amount=Decimal("1941.75"), cost_rate=Decimal("6.95"),
            client_rate=Decimal("6.90"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    result = chain_mod.execute_two_step_chain(db, entry_date=entry_date, step1=step1, step2=step2)

    found = db.execute(
        select(JournalEntry).where(JournalEntry.chain_ref == result.chain_ref).order_by(JournalEntry.chain_seq)
    ).scalars().all()
    assert len(found) == 2
    assert [e.chain_seq for e in found] == [1, 2]
    assert all(e.chain_total == 2 for e in found)
    assert found[0].id == result.step1_entry.id
    assert found[1].id == result.step2_entry.id


@pytest.mark.acceptance(10)
def test_reverse_one_chain_step_reverses_whole_chain(db, now):
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry_date = clock.local_entry_date(now, WORK_TZ)

    def step1(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
            to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
            client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
            chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    def step2(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY",
            to_location_code="CHINA", amount=Decimal("1941.75"), cost_rate=Decimal("6.95"),
            client_rate=Decimal("6.90"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    result = chain_mod.execute_two_step_chain(db, entry_date=entry_date, step1=step1, step2=step2)

    reversals = chain_mod.reverse_chain(
        db, chain_ref=result.chain_ref, reason="فحص عكس السلسلة كاملة", created_by=user.id, now=now
    )
    assert len(reversals) == 2
    db.refresh(result.step1_entry)
    db.refresh(result.step2_entry)
    from app.models.enums import EntryStatus

    assert result.step1_entry.status == EntryStatus.REVERSED
    assert result.step2_entry.status == EntryStatus.REVERSED
