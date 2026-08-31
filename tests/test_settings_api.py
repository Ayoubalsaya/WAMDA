"""اختبارات HTTP للإعدادات (`app/routers/settings.py`، `app/routers/partners.py`، §٧-١٤)."""

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


def test_company_profile_defaults_when_unset(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.get("/settings/company")
    assert resp.status_code == 200
    assert resp.json()["name_ar"] == "ومضة"


def test_accountant_cannot_write_company_profile(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.put("/settings/company", json={"name_ar": "شركة تجريبية"}, headers=_headers(client))
    assert resp.status_code == 403


def test_admin_updates_company_profile_and_it_persists(db, client):
    _login(db, client, role="ADMIN")
    resp = client.put("/settings/company", json={"name_ar": "ومضة للصرافة والحوالات"}, headers=_headers(client))
    assert resp.status_code == 200
    assert resp.json()["name_ar"] == "ومضة للصرافة والحوالات"

    resp2 = client.get("/settings/company")
    assert resp2.json()["name_ar"] == "ومضة للصرافة والحوالات"


def test_list_partners_empty_then_created(db, client):
    _login(db, client, role="ADMIN")
    resp = client.get("/partners")
    assert resp.status_code == 200

    create = client.post(
        "/partners",
        json={"code": f"PART-{f.uid()}", "name_ar": "شريك تركيا الجديد", "country": "TR"},
        headers=_headers(client),
    )
    assert create.status_code == 201, create.text
    partner_id = create.json()["id"]

    listing = client.get("/partners")
    assert any(p["id"] == partner_id for p in listing.json())


def test_accountant_cannot_create_partner(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(
        "/partners", json={"code": f"PART-{f.uid()}", "name_ar": "شريك", "country": "TR"}, headers=_headers(client),
    )
    assert resp.status_code == 403


def test_duplicate_partner_code_conflict(db, client):
    _login(db, client, role="ADMIN")
    code = f"PART-{f.uid()}"
    resp1 = client.post("/partners", json={"code": code, "name_ar": "شريك أول", "country": "TR"}, headers=_headers(client))
    assert resp1.status_code == 201
    resp2 = client.post("/partners", json={"code": code, "name_ar": "شريك ثانٍ", "country": "TR"}, headers=_headers(client))
    assert resp2.status_code == 409
