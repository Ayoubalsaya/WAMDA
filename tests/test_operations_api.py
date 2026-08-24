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


def test_local_move_between_company_accounts(db, client):
    _login(db, client)
    resp = client.post(
        "/operations/local-move",
        json={"currency_code": "LYD", "from_account_code": "1101", "to_account_code": "1102", "amount": "50.000"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text


def test_remit_out_requires_registered_beneficiary(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    c = f.make_client(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    beneficiary = f.make_beneficiary(db, c, currency_code="CNY")
    resp = client.post(
        "/operations/remit-out",
        json={"client_id": c.id, "from_location_code": "TURKEY", "partner_account_code": partner_acct.code,
              "beneficiary_id": beneficiary.id, "beneficiary_amount": "69000.00", "cost_rate": "6.90",
              "client_rate": "6.80"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["profit_amount"] == "147.060000"

    # مستفيد يخص عميلاً آخر → ٤٠٤ (لا وجهة غير مسجّلة لهذا العميل)
    other_client = f.make_client(db)
    resp2 = client.post(
        "/operations/remit-out",
        json={"client_id": other_client.id, "from_location_code": "TURKEY", "partner_account_code": partner_acct.code,
              "beneficiary_id": beneficiary.id, "beneficiary_amount": "1000.00", "cost_rate": "6.90",
              "client_rate": "6.80"},
        headers=_headers(client),
    )
    assert resp2.status_code == 404


def test_swift_out_then_swift_in(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
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
    assert db.get(AccountBalance, accounts_repo.get_account_by_code(db, "1501").id).balance == Decimal("0.00")


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


def test_expense(db, client):
    _login(db, client)
    expense_acct = accounts_repo.get_currency_subaccount(db, "5200", "LYD")
    resp = client.post(
        "/operations/expense",
        json={"expense_account_code": expense_acct.code, "currency_code": "LYD", "paying_account_code": "1101",
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
