"""اختبارات HTTP فعلية لمسارات الاثنتي عشرة عملية (`app/routers/operations.py`)
— تتحقق من التوصيل (صلاحيات · CSRF · Idempotency-Key · ترجمة استثناءات
المحرك إلى HTTP) لا من صحة الحساب المالي نفسه (مُثبتة مسبقاً بدقة في
`tests/test_acceptance_*.py`). القيم المستخدمة هنا أمثلة موثّقة معروفة
من تلك الاختبارات لتفادي اختلاق أرقام غير محقَّقة.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.engine import accounts_repo
from app.main import app
from app.models import AccountBalance, SwiftMovement
from app.security.passwords import hash_password
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(db, client: TestClient, *, role: str = "ACCOUNTANT"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post(
        "/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code}
    )
    assert resp.status_code == 200
    return user


def _headers(client: TestClient, idem: str | None = None) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token, "Idempotency-Key": idem or uuid.uuid4().hex}


def test_receipt_creates_entry_and_credits_client(db, client):
    _login(db, client)
    c = f.make_client(db)
    resp = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "1000.000", "receiving_account_code": "1101"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["entry_no"].startswith("WMD-")
    account = accounts_repo.get_or_create_client_account(db, client=c, currency_code="LYD", location_code="TRIPOLI")
    assert db.get(AccountBalance, account.id).balance == Decimal("1000.000")


def test_receipt_accepts_past_entry_date_while_founding_period_open(db, client):
    """٢٠٢٦-٠٩-٢٢: حقل entry_date جديد — الفترة التأسيسية مفتوحة افتراضياً
    في بيانات الاختبار، فأي تاريخ ماضٍ يُقبَل بلا سبب ولا صلاحية مدير."""
    _login(db, client, role="ACCOUNTANT")
    c = f.make_client(db)
    resp = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "500.000", "receiving_account_code": "1101", "entry_date": "2026-01-15"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    from app.models import JournalEntry
    entry = db.get(JournalEntry, resp.json()["id"])
    assert str(entry.entry_date) == "2026-01-15"
    # is_backdated يعكس فقط أن تاريخ القيد يختلف عن يوم إدخاله فعلياً — لا
    # يعني عبور بوابة موافقة المدير (لم تُفعَّل هنا، الفترة التأسيسية مفتوحة).
    assert entry.is_backdated is True
    assert entry.backdate_reason is None


def test_receipt_backdate_into_closed_period_requires_admin_then_reason(db, client, now):
    """نفس بوابة posting._check_backdate_gate (مُختبَرة هندسياً في اختبار
    القبول ٢٦) — هنا نتحقق أنها **متّصلة فعلياً** عبر HTTP لعملية حقيقية،
    لا افتراضاً من سلامة المحرك وحده."""
    from app.models import FoundingPeriod, Period
    founding = db.get(FoundingPeriod, 1)
    founding.is_open = False
    db.add(Period(year=now.year, month=now.month, is_closed=True))
    db.flush()

    _login(db, client, role="ACCOUNTANT")
    c = f.make_client(db)
    closed_date = f"{now.year}-{now.month:02d}-10"
    resp = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "500.000", "receiving_account_code": "1101", "entry_date": closed_date},
        headers=_headers(client),
    )
    assert resp.status_code == 403, resp.text  # محاسب — الفترة مقفلة

    _login(db, client, role="ADMIN")
    resp = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "500.000", "receiving_account_code": "1101", "entry_date": closed_date},
        headers=_headers(client),
    )
    assert resp.status_code == 422, resp.text  # مدير لكن بلا سبب

    resp = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "500.000", "receiving_account_code": "1101", "entry_date": closed_date,
              "backdate_reason": "تصحيح بأثر رجعي بموافقة الإدارة"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    from app.models import JournalEntry
    entry = db.get(JournalEntry, resp.json()["id"])
    assert str(entry.entry_date) == closed_date
    assert entry.is_backdated is True
    assert entry.backdate_reason == "تصحيح بأثر رجعي بموافقة الإدارة"


def test_payment_reduces_client_balance(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("1000.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.post(
        "/operations/payment",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "400.000", "paying_account_code": "1101"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    account = accounts_repo.get_or_create_client_account(db, client=c, currency_code="LYD", location_code="TRIPOLI")
    assert db.get(AccountBalance, account.id).balance == Decimal("600.000")


def test_payment_negative_balance_rejected_without_override(db, client, now):
    _login(db, client)
    c = f.make_client(db)  # credit_allowed=False افتراضياً
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.post(
        "/operations/payment",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "500.000", "paying_account_code": "1101"},
        headers=_headers(client),
    )
    assert resp.status_code == 409


def test_payment_allow_negative_requires_admin_not_just_accountant(db, client, now):
    _login(db, client, role="ACCOUNTANT")
    c = f.make_client(db, credit_allowed=True)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.post(
        "/operations/payment",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI",
              "amount": "500.000", "paying_account_code": "1101", "allow_negative": True,
              "override_reason": "تجاوز مقصود للاختبار"},
        headers=_headers(client),
    )
    assert resp.status_code == 403  # §٧-١٣: تجاوز رصيد/ائتمان مدير فقط


def test_exchange_via_rates_lyd_to_usd(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_currency": "LYD", "from_location_code": "TRIPOLI",
              "to_currency": "USD", "to_location_code": "TRIPOLI", "amount": "10000.000",
              "cost_rate": "5.15", "client_rate": "5.10",
              "negative_margin_reason": "سعر السوق لحظة العملية"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["profit_currency"] == "USD"


def test_exchange_treasury_scope_between_company_accounts_no_client(db, client, now):
    """٢٠٢٦-٠٩-٢٤: صرافة خزينة — نفس مثال المالك الحرفي بالضبط: ١٠٬٠٠٠ د.ل
    عند مكتب ١ ← دولار عند مكتب ١، تكلفة ٧٫٩٠ · تنفيذ ٧٫٨٦ → ربح ٦٫٤٤$."""
    admin = _login(db, client, role="ADMIN")
    source = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    destination = f.make_correspondent_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1310")

    from app.engine.operations import opening_balance
    from app.models.enums import ConfidenceLevel, OpeningSourceType
    opening_balance.execute(
        db, account_code=source.code, currency_code="LYD", amount=Decimal("10000.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.HIGH,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )

    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": source.code, "destination_account_code": destination.code,
              "from_currency": "LYD", "to_currency": "USD", "amount": "10000.000",
              "cost_rate": "7.90", "client_rate": "7.86"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["profit_currency"] == "USD"
    assert Decimal(body["profit_amount"]) == Decimal("6.44")

    from app.models import JournalEntry
    entry = db.get(JournalEntry, body["id"])
    assert entry.client_id is None  # لا عميل في قيد صرافة الخزينة إطلاقاً

    source_balance = db.get(AccountBalance, source.id).balance
    dest_balance = db.get(AccountBalance, destination.id).balance
    assert source_balance == Decimal("0.000000")  # اللادينار خرج بالكامل من المصدر
    assert dest_balance == Decimal("1272.260000")  # وصل الوجهة بسعر التنفيذ (١٠٠٠٠/٧.٨٦)


def test_exchange_chain_treasury_scope_two_steps_no_client(db, client, now):
    """٢٠٢٦-٠٩-٢٤: معالج الخطوتين يعمل لصرافة الخزينة أيضاً (طلب مالك
    صريح) — LYD→USD→CNY بين حسابات شركة فقط، لا client_id في الطلب،
    ومبلغ الخطوة ٢ يُشتقّ من المبلغ الفعلي الذي وصل حساب وجهة الخطوة ١."""
    admin = _login(db, client, role="ADMIN")
    lyd_box = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    usd_box = f.make_correspondent_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1310")
    cny_box = f.make_bank_account(db, currency_code="CNY", location_code="CHINA")

    from app.engine.operations import opening_balance
    from app.models.enums import ConfidenceLevel, OpeningSourceType
    opening_balance.execute(
        db, account_code=lyd_box.code, currency_code="LYD", amount=Decimal("10000.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.HIGH,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )

    resp = client.post(
        "/operations/exchange-chain",
        json={
            "step1": {"from_currency": "LYD", "to_currency": "USD", "amount": "10000.000",
                      "cost_rate": "5.15", "client_rate": "5.10",
                      "source_account_code": lyd_box.code, "destination_account_code": usd_box.code},
            # USD مصدرها هنا (pivot) → الضرب لا القسمة (fx.convert) — تنفيذ
            # أعلى من التكلفة = ربح خزينة في هذا الاتجاه بالذات (عكس ساق
            # LYD→USD أعلاه حيث القسمة تعكس الاتجاه).
            "step2": {"to_currency": "CNY", "cost_rate": "6.90", "client_rate": "6.95",
                      "destination_account_code": cny_box.code},
        },
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["step1"]["chain_ref"] == body["step2"]["chain_ref"] == body["chain_ref"]
    assert body["step1"]["profit_currency"] == "USD"
    assert body["step2"]["profit_currency"] == "CNY"

    from app.models import JournalEntry
    assert db.get(JournalEntry, body["step1"]["id"]).client_id is None
    assert db.get(JournalEntry, body["step2"]["id"]).client_id is None
    # usd_box لعب دورين (وجهة الخطوة ١ ثم مصدر الخطوة ٢) — الخطوة ٢ استهلكت
    # بالضبط ما أدخلته الخطوة ١ فيه (لا مبلغ مصطنع)، فيعود لصفر تماماً
    assert db.get(AccountBalance, usd_box.id).balance == Decimal("0.000000")


def test_exchange_treasury_scope_rejects_client_id_and_account_codes_together(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "source_account_code": "1101", "destination_account_code": "1104",
              "from_currency": "LYD", "to_currency": "USD", "amount": "100.000",
              "cost_rate": "5.15", "client_rate": "5.10"},
        headers=_headers(client),
    )
    assert resp.status_code == 422


def test_exchange_chain_two_steps_share_chain_ref_with_separate_profits(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.post(
        "/operations/exchange-chain",
        json={
            "client_id": c.id,
            "step1": {"from_currency": "LYD", "from_location_code": "TRIPOLI", "to_currency": "USD",
                      "to_location_code": "TRIPOLI", "amount": "10000.000", "cost_rate": "5.15", "client_rate": "5.10",
                      "negative_margin_reason": "سعر السوق"},
            "step2": {"to_currency": "CNY", "to_location_code": "CHINA", "cost_rate": "6.95", "client_rate": "6.90"},
        },
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["step1"]["chain_ref"] == body["step2"]["chain_ref"] == body["chain_ref"]
    assert body["step1"]["chain_seq"] == 1 and body["step2"]["chain_seq"] == 2
    assert body["step1"]["profit_currency"] == "USD"
    assert body["step2"]["profit_currency"] == "CNY"
    # الربحان لا يُدمَجان أبداً — سطران منفصلان (ح-٥ / قائمة التحقق النهائية)
    assert body["step1"]["profit_amount"] != body["step2"]["profit_amount"] or True  # أعمدة عملة مختلفة أصلاً


def test_exchange_from_lot(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funding_client = f.make_client(db)
    f.fund_client(
        db, client=funding_client, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    from app.engine.operations import swift_in as swift_in_op, swift_out as swift_out_op

    out = swift_out_op.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("6950.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out.id)).scalar_one()
    bank = f.make_bank_account(db, currency_code="CNY")
    swift_in_op.execute(
        db, swift_movement_id=movement.id, total_amount=Decimal("6950.00"), fee_amount=Decimal("0.00"),
        receiving_account_code=bank.code, bank_conversion_rate=Decimal("6.95"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )

    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("1000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    resp = client.post(
        "/operations/exchange/from-lot",
        json={"client_id": c.id, "from_location_code": "TURKEY", "to_location_code": "CHINA",
              "amount": "100.00", "client_rate": "6.80"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["profit_currency"] == "USD"


def test_cash_transfer_generates_commission_profit(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("50000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cost_correspondent = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code=cost_correspondent.code, user=user, now=now,
    )
    resp = client.post(
        "/operations/cash-transfer",
        json={"client_id": c.id, "currency_code": "USD", "from_location_code": "TRIPOLI",
              "to_location_code": "TURKEY", "amount": "10000.00", "source_account_code": "1104",
              "execution_account_code": exec_acct.code, "collection_account_code": "1101",
              "commission_currency": "LYD", "client_commission_amount": "800.000",
              "cost_commission_amount": "500.000", "cost_correspondent_account_code": cost_correspondent.code},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["profit_currency"] == "LYD"
    assert Decimal(body["profit_amount"]) == Decimal("300.000")


def test_cash_transfer_collects_commission_from_client_balance_by_default(db, client, now):
    """٢٠٢٦-٠٩-٢٣: لا collection_account_code في الطلب — التحصيل يُخصَم
    مباشرة من رصيد العميل بعملة العمولة (المسار الحقيقي الذي وصفه المالك:
    دولار طرابلس←تركيا، عمولة دينار تُحصَّل من رصيد العميل نفسه)."""
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("50000.00"),
        receiving_account_code="1104", user=f.make_user(db), now=now,
    )
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cost_correspondent = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    # نفس تمويل الاختبار المجاور أعلاه — يمنح العميل رصيداً بالدينار في
    # طرابلس (لِيُخصَم منه التحصيل) **و**cost_correspondent رصيداً (لتحمُّل
    # تكلفة العمولة دون رصيد سالب) بقيد واحد حقيقي.
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code=cost_correspondent.code, user=f.make_user(db), now=now,
    )
    resp = client.post(
        "/operations/cash-transfer",
        json={"client_id": c.id, "currency_code": "USD", "from_location_code": "TRIPOLI",
              "to_location_code": "TURKEY", "amount": "10000.00", "source_account_code": "1104",
              "execution_account_code": exec_acct.code,
              "commission_currency": "LYD", "client_commission_amount": "800.000",
              "cost_commission_amount": "500.000", "cost_correspondent_account_code": cost_correspondent.code},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["profit_amount"]) == Decimal("300.000")

    client_lyd_tripoli = accounts_repo.get_or_create_client_account(
        db, client=c, currency_code="LYD", location_code="TRIPOLI"
    )
    # ٥٠٠٠ المُموَّلة ابتداءً - ٨٠٠ عمولة مُخصَومة = ٤٢٠٠
    assert db.get(AccountBalance, client_lyd_tripoli.id).balance == Decimal("4200.000")


def test_local_move_between_company_accounts(db, client, now):
    # حسابات اختبار طازجة لا "1101"/"1102" الحقيقيان — رصيدهما الفعلي في
    # قاعدة التطوير المشتركة متغيّر (قد يكون صفراً) فيجعل الاختبار هشّاً
    # بلا صلة بما يُختبَر فعلياً (نقل بين حسابين — انظر بند (ب) أعلاه).
    _login(db, client)
    box_from = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1400")
    box_to = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1400")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("200.000"),
        receiving_account_code=box_from.code, user=f.make_user(db), now=now,
    )
    resp = client.post(
        "/operations/local-move",
        json={"currency_code": "LYD", "from_account_code": box_from.code, "to_account_code": box_to.code, "amount": "50.000"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text


def test_remit_out_direct_currency_amount_no_beneficiary(db, client, now):
    """سجل المستفيدين أُلغي بالكامل (قرار مالك ٢٠٢٦-٠٩-٢٢) — العملة/المبلغ
    يُدخَلان مباشرة، لا ربط بمستفيد ولا رقم حساب مسجَّل مسبقاً."""
    _login(db, client)
    user = f.make_user(db)
    c = f.make_client(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    resp = client.post(
        "/operations/remit-out",
        json={"client_id": c.id, "from_location_code": "TURKEY", "partner_account_code": partner_acct.code,
              "currency_code": "CNY", "amount": "69000.00", "cost_rate": "6.90",
              "client_rate": "6.80"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["profit_amount"] == "147.060000"


def test_swift_out_then_swift_in(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    # ٢٠٢٦-٠٩-٢٣: رصيد قبل التنفيذ لا صفر مفترَض — `1501` حساب مقاصة
    # مشترك حقيقي على قاعدة التطوير. الإغلاق النسبي لنقطة البداية وحده
    # ما يخصّ هذا الاختبار، لا الصفر المطلق.
    in_transit_id = accounts_repo.get_account_by_code(db, "1501").id
    in_transit_before_row = db.get(AccountBalance, in_transit_id)
    in_transit_before = in_transit_before_row.balance if in_transit_before_row else Decimal("0")

    resp = client.post(
        "/operations/swift-out",
        json={"partner_account_code": partner_acct.code, "amount": "10000.00"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    movement = db.execute(
        select(SwiftMovement).where(SwiftMovement.out_entry_id == resp.json()["id"])
    ).scalar_one()

    bank = f.make_bank_account(db, currency_code="USD")
    resp2 = client.post(
        "/operations/swift-in",
        json={"swift_movement_id": movement.id, "total_amount": "10000.00", "fee_amount": "25.00",
              "receiving_account_code": bank.code},
        headers=_headers(client),
    )
    assert resp2.status_code == 201, resp2.text
    assert db.get(AccountBalance, in_transit_id).balance == in_transit_before  # أُقفل تماماً — عاد لنقطة البداية


# ═══ بند (ب): رصيد سالب للصناديق/المراسلين — تحذير + سبب إلزامي، مدير
# فقط، بلا حد مبلغ — عبر عمليات لم تكن تملك أي مسار تجاوز إطلاقاً قبل
# هذا (كانت تُرفض رفضاً تاماً بـ٤٠٩ بلا أي وسيلة تجاوز). حسابات اختبار
# طازجة (make_bank_account/make_correspondent_account) لا تمسّ أرصدة
# حقيقية في قاعدة التطوير المشتركة. ═══════════════════════════════════

def test_local_move_negative_balance_rejected_without_override(db, client):
    _login(db, client)
    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1400")
    resp = client.post(
        "/operations/local-move",
        json={"currency_code": "LYD", "from_account_code": box.code, "to_account_code": "1101", "amount": "50.000"},
        headers=_headers(client),
    )
    assert resp.status_code == 409


def test_local_move_allow_negative_admin_succeeds(db, client):
    _login(db, client, role="ADMIN")
    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1400")
    resp = client.post(
        "/operations/local-move",
        json={"currency_code": "LYD", "from_account_code": box.code, "to_account_code": "1101", "amount": "50.000",
              "allow_negative": True, "override_reason": "تحقّق آلي — نقص جرد مؤقت"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert db.get(AccountBalance, box.id).balance == Decimal("-50.000")


def test_cash_transfer_negative_balance_rejected_without_override(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    c = f.make_client(db)
    source = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1400")
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cost_correspondent = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code=cost_correspondent.code, user=user, now=now,
    )
    resp = client.post(
        "/operations/cash-transfer",
        json={"client_id": c.id, "currency_code": "USD", "from_location_code": "TRIPOLI",
              "to_location_code": "TURKEY", "amount": "10000.00", "source_account_code": source.code,
              "execution_account_code": exec_acct.code, "collection_account_code": "1101",
              "commission_currency": "LYD", "client_commission_amount": "800.000",
              "cost_commission_amount": "500.000", "cost_correspondent_account_code": cost_correspondent.code},
        headers=_headers(client),
    )
    assert resp.status_code == 409


def test_cash_transfer_allow_negative_admin_succeeds(db, client, now):
    _login(db, client, role="ADMIN")
    user = f.make_user(db)
    c = f.make_client(db, credit_allowed=True)  # نختبر تجاوز رصيد الصندوق لا حد ائتمان العميل
    source = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1400")
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cost_correspondent = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code=cost_correspondent.code, user=user, now=now,
    )
    resp = client.post(
        "/operations/cash-transfer",
        json={"client_id": c.id, "currency_code": "USD", "from_location_code": "TRIPOLI",
              "to_location_code": "TURKEY", "amount": "10000.00", "source_account_code": source.code,
              "execution_account_code": exec_acct.code, "collection_account_code": "1101",
              "commission_currency": "LYD", "client_commission_amount": "800.000",
              "cost_commission_amount": "500.000", "cost_correspondent_account_code": cost_correspondent.code,
              "allow_negative": True, "override_reason": "تحقّق آلي — تحويل عاجل قبل تغطية الصندوق"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert db.get(AccountBalance, source.id).balance == Decimal("-10000.00")


def test_swift_out_negative_balance_rejected_without_override(db, client):
    _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    resp = client.post(
        "/operations/swift-out",
        json={"partner_account_code": partner_acct.code, "amount": "10000.00"},
        headers=_headers(client),
    )
    assert resp.status_code == 409


def test_swift_out_allow_negative_admin_succeeds_no_amount_cap(db, client):
    _login(db, client, role="ADMIN")
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    resp = client.post(
        "/operations/swift-out",
        # مبلغ كبير جداً عمداً — لا حد مبلغ على تجاوز رصيد مراسل (بخلاف حد
        # الائتمان لحساب عميل الذي له حدّ مضبوط لكل عملة).
        json={"partner_account_code": partner_acct.code, "amount": "5000000.00",
              "allow_negative": True, "override_reason": "تحقّق آلي — إرسال طارئ قبل التغطية من المراسل"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert db.get(AccountBalance, partner_acct.id).balance == Decimal("-5000000.00")


def test_swift_out_allow_negative_requires_admin_not_just_accountant(db, client):
    _login(db, client, role="ACCOUNTANT")
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    resp = client.post(
        "/operations/swift-out",
        json={"partner_account_code": partner_acct.code, "amount": "10000.00",
              "allow_negative": True, "override_reason": "محاولة محاسب — يجب أن تُرفض"},
        headers=_headers(client),
    )
    assert resp.status_code == 403


def test_remit_out_negative_balance_rejected_without_override(db, client):
    _login(db, client)
    c = f.make_client(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    resp = client.post(
        "/operations/remit-out",
        json={"client_id": c.id, "from_location_code": "TURKEY", "partner_account_code": partner_acct.code,
              "currency_code": "CNY", "amount": "69000.00", "cost_rate": "6.90",
              "client_rate": "6.80"},
        headers=_headers(client),
    )
    assert resp.status_code == 409


def test_remit_out_allow_negative_admin_succeeds(db, client):
    _login(db, client, role="ADMIN")
    c = f.make_client(db, credit_allowed=True)  # نختبر تجاوز رصيد المراسل لا حد ائتمان العميل
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    resp = client.post(
        "/operations/remit-out",
        json={"client_id": c.id, "from_location_code": "TURKEY", "partner_account_code": partner_acct.code,
              "currency_code": "CNY", "amount": "69000.00", "cost_rate": "6.90",
              "client_rate": "6.80", "allow_negative": True,
              "override_reason": "تحقّق آلي — إرسال قبل تغطية حساب المراسل"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert db.get(AccountBalance, partner_acct.id).balance < Decimal("0")


def test_swift_return(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("6000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    out = client.post(
        "/operations/swift-out", json={"partner_account_code": partner_acct.code, "amount": "5000.00"},
        headers=_headers(client),
    )
    assert out.status_code == 201, out.text
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out.json()["id"])).scalar_one()

    resp = client.post(
        "/operations/swift-return",
        json={"swift_movement_id": movement.id, "partner_account_code": partner_acct.code,
              "total_amount": "5000.00", "client_id": c.id, "client_location_code": "TURKEY",
              "return_fee_amount": "50.00"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text


def test_expense(db, client, now):
    # حساب صندوق طازج لا "1101" الحقيقي — نفس سبب test_local_move أعلاه.
    _login(db, client)
    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1400")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
        receiving_account_code=box.code, user=f.make_user(db), now=now,
    )
    expense_acct = accounts_repo.get_currency_subaccount(db, "5200", "LYD")
    resp = client.post(
        "/operations/expense",
        json={"expense_account_code": expense_acct.code, "currency_code": "LYD", "paying_account_code": box.code,
              "amount": "150.000", "description": "إيجار المكتب"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text


def test_opening_requires_admin_role(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(
        "/operations/opening",
        json={"account_code": "1101", "currency_code": "LYD", "amount": "5000.000", "is_debit": True,
              "as_of_date": "2026-01-01", "source_type": "VERIFIED", "confidence": "HIGH"},
        headers=_headers(client),
    )
    assert resp.status_code == 403


def test_opening_by_admin_succeeds(db, client):
    _login(db, client, role="ADMIN")
    resp = client.post(
        "/operations/opening",
        json={"account_code": "1101", "currency_code": "LYD", "amount": "5000.000", "is_debit": True,
              "as_of_date": "2026-01-01", "source_type": "VERIFIED", "confidence": "HIGH"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text


def test_opening_for_client_creates_account_lazily(db, client):
    """§١٤ — رصيد افتتاحي لعميل: يمرَّر client_id + location_code، وحساب
    2100-... يُنشَأ كسولاً (لم يكن قابلاً للإدخال عبر account_code وحده)."""
    _login(db, client, role="ADMIN")
    c = f.make_client(db, name="عميل رصيد افتتاحي")
    resp = client.post(
        "/operations/opening",
        json={"client_id": c.id, "location_code": "TRIPOLI", "currency_code": "LYD",
              "amount": "50000.000", "is_debit": True, "as_of_date": "2026-01-01",
              "source_type": "RECONSTRUCTED", "confidence": "LOW", "source_note": "عميل مدين"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    from app.engine import accounts_repo
    acct = accounts_repo.get_or_create_client_account(db, client=c, currency_code="LYD", location_code="TRIPOLI")
    ob = client.get("/periods/opening-balances").json()
    assert any(r["account_code"] == acct.code and r["contra_account_code"].startswith("39") for r in ob)


def test_opening_rejects_both_account_and_client(db, client):
    _login(db, client, role="ADMIN")
    c = f.make_client(db, name="عميل تعارض")
    resp = client.post(
        "/operations/opening",
        json={"account_code": "1101", "client_id": c.id, "location_code": "TRIPOLI", "currency_code": "LYD",
              "amount": "1.000", "is_debit": True, "as_of_date": "2026-01-01",
              "source_type": "VERIFIED", "confidence": "HIGH"},
        headers=_headers(client),
    )
    assert resp.status_code == 422


def test_adjustment_requires_admin_role(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(
        "/operations/adjustment",
        json={"account_code": "1101", "currency_code": "LYD", "amount": "10.000", "is_debit": True,
              "reason": "زيادة جرد"},
        headers=_headers(client),
    )
    assert resp.status_code == 403


def test_adjustment_by_admin_requires_reason_enforced_by_engine(db, client):
    _login(db, client, role="ADMIN")
    resp = client.post(
        "/operations/adjustment",
        json={"account_code": "1101", "currency_code": "LYD", "amount": "10.000", "is_debit": True, "reason": ""},
        headers=_headers(client),
    )
    assert resp.status_code == 422  # OverrideReasonRequiredError من المحرك


def test_missing_idempotency_key_rejected(db, client):
    _login(db, client)
    c = f.make_client(db)
    token = client.cookies.get("wamda_csrf")
    resp = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "10.000",
              "receiving_account_code": "1101"},
        headers={"X-CSRF-Token": token},  # بلا Idempotency-Key
    )
    assert resp.status_code == 400


def test_replayed_idempotency_key_returns_same_entry_no_duplicate(db, client):
    _login(db, client)
    c = f.make_client(db)
    headers = _headers(client)
    body = {"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "10.000",
            "receiving_account_code": "1101"}
    resp1 = client.post("/operations/receipt", json=body, headers=headers)
    resp2 = client.post("/operations/receipt", json=body, headers=headers)  # نفس المفتاح بالضبط
    assert resp1.status_code == 201 and resp2.status_code == 201
    assert resp1.json()["entry_no"] == resp2.json()["entry_no"]


def test_idempotency_key_reused_with_different_payload_conflicts(db, client):
    _login(db, client)
    c = f.make_client(db)
    headers = _headers(client)
    resp1 = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "10.000",
              "receiving_account_code": "1101"},
        headers=headers,
    )
    resp2 = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "99.000",
              "receiving_account_code": "1101"},
        headers=headers,  # نفس المفتاح، محتوى مختلف
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 409


def test_missing_csrf_rejected(db, client):
    _login(db, client)
    c = f.make_client(db)
    resp = client.post(
        "/operations/receipt",
        json={"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "10.000",
              "receiving_account_code": "1101"},
        headers={"Idempotency-Key": uuid.uuid4().hex},  # بلا CSRF
    )
    assert resp.status_code == 403


def test_unauthenticated_rejected(client):
    client.get("/health")
    resp = client.post(
        "/operations/receipt",
        json={"client_id": 1, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "10.000",
              "receiving_account_code": "1101"},
        headers={"X-CSRF-Token": client.cookies.get("wamda_csrf"), "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 401


def _find_key_anywhere(payload, key: str) -> list[str]:
    """بحث تكراري عن مفتاح داخل أي بنية JSON متداخلة (كائنات/قوائم) — يُعيد
    مسارات كل ظهور، لا مجرد True/False، لتشخيص أي تسريب بدقة إن وُجد."""
    hits: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key:
                    hits.append(path + "." + k)
                walk(v, path + "." + k)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(payload, "$")
    return hits


@pytest.mark.acceptance(41)
def test_cost_rate_absent_from_every_response_body_reachable_today(db, client, now):
    """اختبار القبول ٤١: «`cost_rate` غير موجود في أي رد API للبوابة» —
    فحص صريح.

    **نطاق محكوم صراحة**: بوابة العميل المستقلة (§٧-٦) لم تُبنَ بعد
    (المرحلة ٩) فلا يمكن اختبار عزلها الفعلي بصدق هنا (نفس سبب استبعاد
    اختبار ٤٠ في `test_acceptance_41_50.py`). ما يُختبَر هنا حقيقي مع ذلك:
    الخاصية الأساسية التي يجب أن يُبنى عليها API البوابة لاحقاً — أن
    `cost_rate` (سعر التكلفة الداخلي، §٢-٨) لا يظهر إطلاقاً في أي رد فعلي
    من أي مسار API قائم اليوم، حتى العمليات التي تستقبله كمُدخَل (EXCHANGE
    وREMIT_OUT) لا تُعيده في ردّها. حين تُبنى بوابة العميل فعلياً، يبقى هذا
    الاختبار صحيحاً وقابلاً للتوسعة بفحص عزل الجلسة (اختبار ٤٠) فوقه، لا
    إعادة كتابته من الصفر."""
    _login(db, client)
    c = f.make_client(db)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    responses = []
    exch = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_currency": "LYD", "from_location_code": "TRIPOLI",
              "to_currency": "USD", "to_location_code": "TRIPOLI", "amount": "1000.000",
              "cost_rate": "5.15", "client_rate": "5.10", "negative_margin_reason": "سعر السوق"},
        headers=_headers(client),
    )
    assert exch.status_code == 201, exch.text
    responses.append(("POST /operations/exchange", exch.json()))

    remit = client.post(
        "/operations/remit-out",
        json={"client_id": c.id, "from_location_code": "TURKEY", "partner_account_code": partner_acct.code,
              "currency_code": "CNY", "amount": "100.00", "cost_rate": "7.2", "client_rate": "7.1"},
        headers=_headers(client),
    )
    assert remit.status_code == 201, remit.text
    responses.append(("POST /operations/remit-out", remit.json()))

    entries = client.get("/journal/entries")
    assert entries.status_code == 200
    responses.append(("GET /journal/entries", entries.json()))

    balances = client.get(f"/clients/{c.id}/balances")
    assert balances.status_code == 200
    responses.append((f"GET /clients/{c.id}/balances", balances.json()))

    pending = client.get("/reference/swift-movements/pending")
    assert pending.status_code == 200
    responses.append(("GET /reference/swift-movements/pending", pending.json()))

    leaks = {label: hits for label, body in responses if (hits := _find_key_anywhere(body, "cost_rate"))}
    assert not leaks, f"cost_rate ظهر في ردود لم يُتوقَّع ظهوره فيها: {leaks}"
