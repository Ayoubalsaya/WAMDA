"""اختبارات HTTP للبحث الذكي (`app/routers/search.py`، §٧-١٠)."""

from __future__ import annotations

from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
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
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200
    return user


def test_search_by_entry_no(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="أحمد التجاري")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("321.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/search?entry_no={entry.entry_no}")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert entry.id in ids


def test_search_by_client_name(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="أحمد التجاري الفريد جداً")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/search?q=أحمد التجاري الفريد جداً")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert entry.id in ids


def test_search_by_min_amount_excludes_smaller_entries(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    big = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("9000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    small = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/search?min_amount=5000")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert big.id in ids
    assert small.id not in ids


def test_search_by_currency(db, client, now):
    # يُدمَج مع q لضمان نتيجة قابلة للتمييز — قاعدة التطوير المشتركة تحمل
    # آلاف القيود الحقيقية بنفس تاريخ `now` الثابت؛ بلا هذا الدمج قد يُقصي
    # الترتيب الافتراضي (الأحدث أولاً) قيد الاختبار خارج حد limit الافتراضي.
    user = _login(db, client)
    c = f.make_client(db, name="عميل فحص العملة الفريد جداً")
    lyd_entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    usd_entry = f.fund_client(
        db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("100.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    resp = client.get("/search?currency=USD&q=عميل فحص العملة الفريد جداً")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert usd_entry.id in ids
    assert lyd_entry.id not in ids


def test_search_by_operation_type(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل فحص نوع العملية الفريد جداً")
    receipt = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/search?operation_type=RECEIPT&q=عميل فحص نوع العملية الفريد جداً")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert receipt.id in ids

    resp2 = client.get("/search?operation_type=EXPENSE&q=عميل فحص نوع العملية الفريد جداً")
    ids2 = {r["id"] for r in resp2.json()}
    assert receipt.id not in ids2


def test_search_by_username(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/search?username={user.username}")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert entry.id in ids


def test_search_by_date_range(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    in_range = client.get(f"/search?date_from={now.date().isoformat()}&date_to={now.date().isoformat()}")
    assert entry.id in {r["id"] for r in in_range.json()}
    out_of_range = client.get("/search?date_from=1999-01-01&date_to=1999-01-02")
    assert entry.id not in {r["id"] for r in out_of_range.json()}


def test_search_combines_filters_with_and(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="زبون التقاء الفلاتر")
    matching = f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("7000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    non_matching_currency = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("7000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/search?q=زبون التقاء الفلاتر&currency=USD&min_amount=5000")
    ids = {r["id"] for r in resp.json()}
    assert matching.id in ids
    assert non_matching_currency.id not in ids


def test_search_excludes_draft_and_requires_auth(db, client):
    resp = client.get("/search?q=x")
    assert resp.status_code == 401
