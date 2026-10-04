"""الصرافة بعملتين مختلفتين فقط + معقولية السعر (٢٠٢٦-١٠-٠٤، علّة: صرف USD إلى USD أظهر ربحاً 159.49 وأخرج 1595 USD ليُدخل 0.01)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import get_db
from app.engine.fx import SAME_CURRENCY_MESSAGE
from app.main import app
from app.models import JournalEntry
from app.security.passwords import hash_password
from tests import factories as f

SAME_MSG = "الصرف بين عملتين مختلفتين فقط. لنقل المبلغ بين حساباتك استخدم التحويل"


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


def _entries(db):
    return db.execute(select(func.count()).select_from(JournalEntry)).scalar_one()


def _client_with_usd(db, now, user):
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"),
                  receiving_account_code="1104", user=user, now=now)
    return c


def test_message_constant_is_the_owner_text():
    assert SAME_CURRENCY_MESSAGE == SAME_MSG


def test_client_scope_same_currency_rejected_in_arabic_without_any_entry(db, client, now):
    user = _login(db, client)
    c = _client_with_usd(db, now, user)
    before = _entries(db)
    r = client.post("/operations/exchange", json={
        "client_id": c.id, "from_currency": "USD", "from_location_code": "TRIPOLI", "to_currency": "USD", "to_location_code": "TRIPOLI",
        "amount": "1595", "cost_rate": "0.00001", "client_rate": "0.00001", "negative_margin_reason": "x"}, headers=_h(client))
    assert r.status_code == 422 and r.json()["detail"] == SAME_MSG, r.text
    assert _entries(db) == before


def test_treasury_scope_same_currency_rejected(db, client, now):
    _login(db, client)
    before = _entries(db)
    r = client.post("/operations/exchange", json={
        "source_account_code": "1104", "destination_account_code": "1104", "from_currency": "USD", "to_currency": "USD",
        "amount": "1595", "client_rate": "0.00001"}, headers=_h(client))
    assert r.status_code == 422 and r.json()["detail"] == SAME_MSG, r.text
    assert _entries(db) == before


def test_chain_that_starts_and_ends_in_the_same_currency_rejected(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
                  receiving_account_code="1101", user=user, now=now)
    before = _entries(db)
    r = client.post("/operations/exchange-chain", json={
        "client_id": c.id,
        "step1": {"from_currency": "LYD", "to_currency": "USD", "amount": "1000", "client_rate": "5.0", "cost_rate": "5.0",
                  "from_location_code": "TRIPOLI", "to_location_code": "TRIPOLI"},
        "step2": {"to_currency": "LYD", "client_rate": "5.0", "cost_rate": "5.0", "to_location_code": "TRIPOLI"}}, headers=_h(client))
    assert r.status_code == 422 and r.json()["detail"] == SAME_MSG, r.text
    assert _entries(db) == before


def test_rate_that_rounds_the_result_to_nothing_rejected_client_scope(db, client, now):
    """1595 USD بسعر 0.00001 ⇒ 0.01595 CNY ⇒ يُقرَّب إلى 0.01 (فقد ٣٧٪): مرفوض ولا قيد."""
    user = _login(db, client)
    c = _client_with_usd(db, now, user)
    before = _entries(db)
    r = client.post("/operations/exchange", json={
        "client_id": c.id, "from_currency": "USD", "from_location_code": "TRIPOLI", "to_currency": "CNY", "to_location_code": "CHINA",
        "amount": "1595", "cost_rate": "0.00001", "client_rate": "0.00001", "negative_margin_reason": "x"}, headers=_h(client))
    assert r.status_code == 422 and "يقارب الصفر" in r.json()["detail"], r.text
    assert _entries(db) == before


def test_rate_that_rounds_to_nothing_rejected_treasury_scope(db, client, now):
    _login(db, client)
    cny = f.make_correspondent_account(db, currency_code="CNY", location_code="CHINA", parent_code="1320")
    usd_in = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
                  receiving_account_code=usd_in.code, user=f.make_user(db), now=now)
    before = _entries(db)
    r = client.post("/operations/exchange", json={
        "source_account_code": usd_in.code, "destination_account_code": cny.code, "from_currency": "USD", "to_currency": "CNY",
        "amount": "1595", "client_rate": "0.00001"}, headers=_h(client))
    assert r.status_code == 422 and "يقارب الصفر" in r.json()["detail"], r.text
    assert _entries(db) == before


def test_zero_result_always_rejected_and_small_but_exact_results_accepted(db, client, now):
    from app.engine import fx

    with pytest.raises(fx.ImplausibleRateError):
        fx.assert_plausible_amount(Decimal("0.0000012"), Decimal("0.00"), "USD")
    fx.assert_plausible_amount(Decimal("0.142857"), Decimal("0.14"), "USD")       # فقد ١٫٩٪ — مقبول
    fx.assert_plausible_amount(Decimal("6.9"), Decimal("6.90"), "CNY")
    with pytest.raises(fx.ImplausibleRateError):
        fx.assert_plausible_amount(Decimal("0.0399"), Decimal("0.03"), "USD")     # فقد ٢٥٪
    with pytest.raises(fx.ImplausibleRateError):
        fx.assert_plausible_amount(Decimal("0.01595"), Decimal("0.01"), "USD")    # الحالة المُبلَّغ عنها


def test_normal_exchange_still_works_in_both_scopes(db, client, now):
    user = _login(db, client)
    c = _client_with_usd(db, now, user)
    r = client.post("/operations/exchange", json={
        "client_id": c.id, "from_currency": "USD", "from_location_code": "TRIPOLI", "to_currency": "CNY", "to_location_code": "CHINA",
        "amount": "1595", "cost_rate": "6.95", "client_rate": "6.90"}, headers=_h(client))
    assert r.status_code == 201, r.text
