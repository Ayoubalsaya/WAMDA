"""طلب الإنشاء الأصلي يُحفظ مع القيد ويُسترجَع كاملاً، وإعادة الإنشاء به مع تغيير المبلغ وحده تحتفظ بكل شيء (٢٠٢٦-١٠-٠٤) — كل أنواع العمليات."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models import JournalEntry, SwiftMovement
from app.security.passwords import hash_password
from tests import factories as f


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(db, client):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    db.flush()
    r = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": pyotp.TOTP(user.totp_secret).now()})
    assert r.status_code == 200, r.text
    return user


def _h(client):
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf"), "Idempotency-Key": uuid.uuid4().hex}


def _same(a, b) -> bool:
    """مساواة قيم الطلب بعد تطبيع الأعداد العشرية (الخادم يُخرج Decimal نصاً)."""
    if isinstance(a, str) and isinstance(b, str):
        try:
            return Decimal(a) == Decimal(b)
        except Exception:
            return a == b
    return a == b


def _check_roundtrip(db, client, url, op_type, payload, amount_key):
    r = client.post(url, json=payload, headers=_h(client))
    assert r.status_code == 201, (op_type, r.text)
    eid = r.json()["id"]
    got = client.get(f"/operations/{eid}/source-request")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["operation_type"] == op_type and body["kind"] == "STANDARD"
    saved = body["request"]
    for key, value in payload.items():
        assert key in saved and _same(saved[key], value), (op_type, key, saved.get(key), value)
    # إعادة الإنشاء بالطلب المحفوظ نفسه مع تغيير المبلغ وحده: كل ما لم يتغيّر يبقى
    edited = {k: v for k, v in saved.items() if v is not None}
    edited[amount_key] = str(Decimal(str(payload[amount_key])) + Decimal("1"))
    edit = client.post(f"/operations/{eid}/edit", json={"reason": "تصحيح المبلغ", "operation": edited},
                       headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")})
    assert edit.status_code == 200, (op_type, edit.text)
    new = db.get(JournalEntry, edit.json()["new_entry"]["id"])
    for key, value in edited.items():
        assert key in new.source_request and _same(new.source_request[key], value), (op_type, key)
    assert new.note == payload.get("note")
    return eid, new


def test_receipt_payment_remit_expense_local_move(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"), receiving_account_code="1101", user=user, now=now)
    _check_roundtrip(db, client, "/operations/receipt", "RECEIPT", {
        "client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "100.000", "receiving_account_code": "1101", "note": "ملاحظة قبض"}, "amount")
    _check_roundtrip(db, client, "/operations/payment", "PAYMENT", {
        "client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "50.000", "paying_account_code": "1101", "note": "ملاحظة صرف"}, "amount")
    from app.engine import accounts_repo

    expense = accounts_repo.get_currency_subaccount(db, "5200", "LYD")
    _check_roundtrip(db, client, "/operations/expense", "EXPENSE", {
        "expense_account_code": expense.code, "currency_code": "LYD", "paying_account_code": "1101", "amount": "150.000", "description": "إيجار", "note": "ملاحظة مصروف"}, "amount")
    box_to = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1400")
    _check_roundtrip(db, client, "/operations/local-move", "LOCAL_MOVE", {
        "currency_code": "LYD", "from_account_code": "1101", "to_account_code": box_to.code, "amount": "50.000", "fee_amount": "1.000", "note": "نقل"}, "amount")
    yuan = f.make_correspondent_account(db, currency_code="CNY", location_code="CHINA", parent_code="1320")
    f.fund_client(db, client=c, currency_code="CNY", location_code="CHINA", amount=Decimal("9000.00"), receiving_account_code=yuan.code, user=user, now=now)
    _check_roundtrip(db, client, "/operations/remit-out", "REMIT_OUT", {
        "client_id": c.id, "from_location_code": "CHINA", "sending_account_code": yuan.code, "currency_code": "CNY", "amount": "500.00", "note": "تاجر 998877"}, "amount")


def test_exchange_client_and_treasury_keep_their_commission(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"), receiving_account_code="1104", user=user, now=now)
    eid, new = _check_roundtrip(db, client, "/operations/exchange", "EXCHANGE", {
        "client_id": c.id, "from_currency": "USD", "from_location_code": "TRIPOLI", "to_currency": "CNY", "to_location_code": "CHINA",
        "amount": "1000", "cost_rate": "6.95", "client_rate": "6.90", "commission_direction": "IN", "commission_currency": "LYD",
        "commission_amount": "25.000", "commission_account_code": "1101", "note": "صرافة بعمولة"}, "amount")
    assert (new.commission_direction, new.commission_currency, new.commission_amount) == ("IN", "LYD", Decimal("25.000000")), "العمولة بقيت بعد تعديل المبلغ"
    usd = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cny = f.make_correspondent_account(db, currency_code="CNY", location_code="CHINA", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("9000.00"), receiving_account_code=usd.code, user=user, now=now)
    _, new2 = _check_roundtrip(db, client, "/operations/exchange", "EXCHANGE", {
        "source_account_code": usd.code, "destination_account_code": cny.code, "from_currency": "USD", "to_currency": "CNY", "amount": "1000",
        "client_rate": "6.9", "commission_direction": "OUT", "commission_currency": "USD", "commission_amount": "12", "commission_account_code": usd.code,
        "note": "خزينة بعمولة"}, "amount")
    assert (new2.commission_direction, new2.commission_currency) == ("OUT", "USD")


def test_cash_transfer_swift_opening_adjustment(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("90000.00"), receiving_account_code="1104", user=user, now=now)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50000.000"), receiving_account_code="1101", user=user, now=now)
    cost_corr = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="LYD", location_code="TRIPOLI", amount=Decimal("9000.000"), receiving_account_code=cost_corr.code, user=user, now=now)
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("90000.00"), receiving_account_code=exec_acct.code, user=user, now=now)
    for variant, extra in (("company", {"collection_account_code": "1101"}), ("client", {"collection_location_code": "TRIPOLI"})):
        _check_roundtrip(db, client, "/operations/cash-transfer", "CASH_TRANSFER", {
            "client_id": c.id, "currency_code": "USD", "from_location_code": "TRIPOLI", "to_location_code": "TURKEY", "amount": "10000.00",
            "source_account_code": "1104", "execution_account_code": exec_acct.code, "commission_currency": "LYD", "client_commission_amount": "800.000",
            "cost_commission_amount": "500.000", "cost_correspondent_account_code": cost_corr.code, "note": f"تحويل {variant}", **extra}, "amount")

    partner = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("90000.00"), receiving_account_code=partner.code, user=user, now=now)
    eid, _ = _check_roundtrip(db, client, "/operations/swift-out", "SWIFT_OUT", {
        "partner_account_code": partner.code, "amount": "10000.00", "external_ref": "REF-1", "description": "سويفت", "note": "ملاحظة سويفت"}, "amount")

    out2 = client.post("/operations/swift-out", json={"partner_account_code": partner.code, "amount": "6000.00"}, headers=_h(client))
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out2.json()["id"])).scalar_one()
    bank = f.make_bank_account(db, currency_code="USD")
    _check_roundtrip(db, client, "/operations/swift-in", "SWIFT_IN", {
        "swift_movement_id": movement.id, "total_amount": "6000.00", "fee_amount": "25.00", "receiving_account_code": bank.code, "note": "وصول"}, "total_amount")

    out3 = client.post("/operations/swift-out", json={"partner_account_code": partner.code, "amount": "5000.00"}, headers=_h(client))
    mv3 = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out3.json()["id"])).scalar_one()
    _check_roundtrip(db, client, "/operations/swift-return", "SWIFT_RETURN", {
        "swift_movement_id": mv3.id, "partner_account_code": partner.code, "total_amount": "5000.00", "client_id": c.id, "client_location_code": "TURKEY",
        "return_fee_amount": "50.00", "note": "مرتجع"}, "total_amount")

    _check_roundtrip(db, client, "/operations/opening", "OPENING", {
        "account_code": "1101", "currency_code": "LYD", "amount": "5000.000", "is_debit": True, "as_of_date": "2026-01-01", "source_type": "VERIFIED",
        "confidence": "HIGH", "source_note": "جرد", "note": "رصيد افتتاحي"}, "amount")
    _check_roundtrip(db, client, "/operations/adjustment", "ADJUSTMENT", {
        "account_code": "1101", "currency_code": "LYD", "amount": "10.000", "is_debit": False, "reason": "تسوية جرد", "note": "تسوية", "allow_negative": True}, "amount")


def test_legacy_entry_without_a_saved_request_reports_null(db, client, now):
    """قيد قبل هذه الميزة: request=null فتُنبِّه الواجهة بدل تعبئة مضلِّلة."""
    user = _login(db, client)
    c = f.make_client(db)
    entry = f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10.000"), receiving_account_code="1101", user=user, now=now)
    r = client.get(f"/operations/{entry.id}/source-request")
    assert r.status_code == 200 and r.json()["request"] is None and r.json()["operation_type"] == "RECEIPT"
