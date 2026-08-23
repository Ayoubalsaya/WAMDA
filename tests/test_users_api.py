"""إنشاء مستخدم ثانٍ (بما فيه مدير احتياطي) عبر `POST /users` — المسار
الصحيح الوحيد بعد أول مدير (§٩، تصحيح معتمد): يتطلب جلسة ADMIN فعلية
ويُسجَّل في audit_log بهوية المُنشئ الحقيقية.
"""

from __future__ import annotations

from sqlalchemy import select

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import AuditLog, User
from app.security.deps import SESSION_COOKIE_NAME
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


def _login(db, client: TestClient, *, role: str) -> User:
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    valid_code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post(
        "/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": valid_code}
    )
    assert resp.status_code == 200
    return user


def _csrf_headers(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token}


_NEW_USER_PAYLOAD = {
    "username": "backup-admin-test",
    "full_name": "مدير احتياطي",
    "role": "ADMIN",
    "initial_password": "BackupAdmin!123",
}


def test_create_user_requires_session(client):
    # يتحمّل رمز CSRF صالحاً كي يُختبَر فحص الجلسة تحديداً — بلا كليهما،
    # فحص CSRF (على مستوى المسار) يسبق فحص الجلسة (على مستوى التبعية) فيُخفي المطلوب اختباره هنا خلف 403 عام.
    client.get("/health")
    resp = client.post("/users", json=_NEW_USER_PAYLOAD, headers=_csrf_headers(client))
    assert resp.status_code == 401


def test_create_user_requires_csrf(db, client):
    _login(db, client, role="ADMIN")
    resp = client.post("/users", json=_NEW_USER_PAYLOAD)  # بلا ترويسة CSRF
    assert resp.status_code == 403


def test_create_user_rejects_accountant_role(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.post("/users", json=_NEW_USER_PAYLOAD, headers=_csrf_headers(client))
    assert resp.status_code == 403


def test_admin_creates_second_admin_logged_in_audit(db, client):
    admin = _login(db, client, role="ADMIN")

    resp = client.post("/users", json=_NEW_USER_PAYLOAD, headers=_csrf_headers(client))
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "backup-admin-test"
    assert body["role"] == "ADMIN"

    new_user = db.execute(select(User).where(User.username == "backup-admin-test")).scalar_one()
    assert new_user.must_change_password is True

    audit_row = db.execute(
        select(AuditLog).where(AuditLog.entity == "users", AuditLog.entity_id == new_user.id)
    ).scalar_one()
    assert audit_row.action == "USER_CREATED"
    assert audit_row.actor_id == admin.id  # هوية المُنشئ الحقيقية، لا افتراض
    assert audit_row.after_json["created_by_username"] == admin.username


def test_create_user_duplicate_username_conflict(db, client):
    _login(db, client, role="ADMIN")
    resp1 = client.post("/users", json=_NEW_USER_PAYLOAD, headers=_csrf_headers(client))
    assert resp1.status_code == 201

    resp2 = client.post("/users", json=_NEW_USER_PAYLOAD, headers=_csrf_headers(client))
    assert resp2.status_code == 409
