"""اختبارات إنشاء الحسابات المالية الحقيقية للشركاء (١٣١٠/١٣٢٠) والبنوك
المملوكة (١٤٠٠) — الفجوة الثانية المفتوحة من مراجعة المرحلة ٩، بترقيم
آلي صحيح (`app.engine.accounts_repo.create_partner_account`/`create_bank_account`)
لا `T-ACC-...` اليدوي المقصور على بيانات الاختبار.
"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
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


def _login(db, client: TestClient, *, role: str = "ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200
    return user


def _headers(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token}


def test_create_partner_account_gets_sequential_real_code(db, client):
    _login(db, client, role="ADMIN")
    partner = client.post(
        "/partners", json={"code": f"PART-{f.uid()}", "name_ar": "شريك تركيا حقيقي", "country": "TR"},
        headers=_headers(client),
    ).json()

    resp = client.post(
        f"/partners/{partner['id']}/accounts",
        json={"parent_code": "1320", "currency_code": "USD", "location_code": "TURKEY"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"].startswith("1320")
    assert len(body["code"]) == 6  # 1320 + لاحقة رقمين (٠١-٩٩) — لا كود مشوَّه (T-ACC-...)
    assert body["partner_id"] == partner["id"]
    assert body["form"] == "CORRESPONDENT"

    listing = client.get(f"/partners/{partner['id']}/accounts")
    assert any(a["id"] == body["id"] for a in listing.json())


def test_partner_account_sequential_codes_dont_collide(db, client):
    _login(db, client, role="ADMIN")
    partner = client.post(
        "/partners", json={"code": f"PART-{f.uid()}", "name_ar": "شريك متعدد الحسابات", "country": "TR"},
        headers=_headers(client),
    ).json()

    codes = set()
    for currency in ("USD", "LYD"):
        resp = client.post(
            f"/partners/{partner['id']}/accounts",
            json={"parent_code": "1320", "currency_code": currency, "location_code": "TURKEY"},
            headers=_headers(client),
        )
        assert resp.status_code == 201
        codes.add(resp.json()["code"])
    assert len(codes) == 2


def test_create_partner_account_rejects_invalid_parent(db, client):
    _login(db, client, role="ADMIN")
    partner = client.post(
        "/partners", json={"code": f"PART-{f.uid()}", "name_ar": "شريك", "country": "TR"}, headers=_headers(client),
    ).json()
    resp = client.post(
        f"/partners/{partner['id']}/accounts",
        json={"parent_code": "1400", "currency_code": "USD", "location_code": "TURKEY"},
        headers=_headers(client),
    )
    assert resp.status_code == 422


def test_accountant_cannot_create_partner_account(db, client):
    _login(db, client, role="ADMIN")
    partner = client.post(
        "/partners", json={"code": f"PART-{f.uid()}", "name_ar": "شريك", "country": "TR"}, headers=_headers(client),
    ).json()
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(
        f"/partners/{partner['id']}/accounts",
        json={"parent_code": "1320", "currency_code": "USD", "location_code": "TURKEY"},
        headers=_headers(client),
    )
    assert resp.status_code == 403


def test_create_bank_account_gets_sequential_real_code(db, client):
    _login(db, client, role="ADMIN")
    resp = client.post(
        "/settings/bank-accounts", json={"currency_code": "CNY", "location_code": "CHINA"}, headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"].startswith("140")
    assert body["form"] == "BANK"
    assert body["partner_id"] is None

    listing = client.get("/settings/bank-accounts")
    assert any(a["id"] == body["id"] for a in listing.json())
