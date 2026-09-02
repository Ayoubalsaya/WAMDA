"""اختبارات شاشة سجل التدقيق العامة (`app/security/audit.py::query_audit_log`،
`app/routers/audit.py`، §٩ المرحلة ١١)."""

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


def test_accountant_cannot_view_audit_log(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.get("/audit-log")
    assert resp.status_code == 403


def test_admin_sees_real_action_with_actor_label(db, client, now):
    admin = _login(db, client, role="ADMIN")
    resp = client.post("/periods/close", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert resp.status_code == 200

    listing = client.get("/audit-log")
    assert listing.status_code == 200
    row = next(r for r in listing.json() if r["action"] == "PERIOD_CLOSED")
    assert row["actor_label"] == admin.username
    assert row["actor_type"] == "USER"
    assert row["after_json"] == {"year": now.year, "month": now.month}


def test_filters_by_entity_and_action(db, client, now):
    _login(db, client, role="ADMIN")
    client.post("/periods/close", json={"year": now.year, "month": now.month}, headers=_headers(client))

    filtered = client.get("/audit-log?entity=periods&action=PERIOD_CLOSED")
    assert filtered.status_code == 200
    assert all(r["entity"] == "periods" and r["action"] == "PERIOD_CLOSED" for r in filtered.json())

    unrelated = client.get("/audit-log?entity=nonexistent-entity-xyz")
    assert unrelated.json() == []


def test_client_actor_resolved_to_client_code(db, client, now):
    """actor_type=CLIENT يُحلَّل إلى كود العميل — لا معرّف رقمي خام."""
    from app.security import audit as audit_module
    from app.models.enums import SessionSubjectType

    admin = _login(db, client, role="ADMIN")
    portal_client = f.make_client(db, name="عميل فحص سجل التدقيق")
    audit_module.log_write(
        db, actor_type=SessionSubjectType.CLIENT, actor_id=portal_client.id, action="PORTAL_LOGIN",
        entity="clients", entity_id=portal_client.id,
    )
    db.commit()

    listing = client.get("/audit-log?action=PORTAL_LOGIN")
    assert listing.status_code == 200
    row = next(r for r in listing.json() if r["action"] == "PORTAL_LOGIN")
    assert row["actor_type"] == "CLIENT"
    assert row["actor_label"] == portal_client.code
