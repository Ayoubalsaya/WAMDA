"""§٩ المرحلة ١٢ — أهم نقطة: تعطيل مستخدم أو تغيير دوره يسري **فوراً** على
جلسته القائمة، لا بعد انتهاء الـ٨ ساعات.

`PATCH /users/{id}` (مدير فقط، مُسجَّل في audit_log، حواجز ضد قفل النظام).
اختبارات حيّة: مستخدم مسجَّل الدخول فعلياً عبر HTTP → المدير يغيّر حالته →
طلبه التالي يُرفض/يتغيّر فوراً.
"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models import AuditLog, User
from app.security.passwords import hash_password
from tests import factories as f


@pytest.fixture()
def db_client(db):
    """مصنع عملاء — كل عميل جِرّة كوكيز مستقلة، نفس جلسة قاعدة البيانات."""
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    made: list[TestClient] = []

    def _make() -> TestClient:
        c = TestClient(app, base_url="https://testserver")
        c.__enter__()
        made.append(c)
        return c

    yield _make
    for c in made:
        c.__exit__(None, None, None)
    app.dependency_overrides.clear()


def _login(db, client: TestClient, *, role: str) -> User:
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


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf")}


def test_disabling_user_rejects_their_next_request_immediately(db, db_client):
    admin_c, victim_c = db_client(), db_client()
    admin = _login(db, admin_c, role="ADMIN")
    victim = _login(db, victim_c, role="ACCOUNTANT")

    # الضحية لديه جلسة صالحة تعمل
    assert victim_c.get("/auth/me").status_code == 200

    r = admin_c.patch(f"/users/{victim.id}", json={"is_active": False}, headers=_csrf(admin_c))
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # الطلب التالي للضحية — مرفوض فوراً، بلا انتظار انتهاء الجلسة
    assert victim_c.get("/auth/me").status_code == 401
    # الجلسة أُبطلت فعلياً في القاعدة (لا مجرّد فحص is_active)
    from app.models import Session as SessionModel
    from app.models.enums import SessionSubjectType
    remaining = db.execute(
        select(SessionModel).where(
            SessionModel.subject_type == SessionSubjectType.USER, SessionModel.subject_id == victim.id
        )
    ).scalars().all()
    assert remaining == []

    audit_row = db.execute(
        select(AuditLog).where(AuditLog.entity == "users", AuditLog.entity_id == victim.id, AuditLog.action == "USER_UPDATED")
    ).scalar_one()
    assert audit_row.actor_id == admin.id
    assert audit_row.before_json["is_active"] is True
    assert audit_row.after_json["is_active"] is False
    assert audit_row.after_json["sessions_revoked"] == 1


def test_role_change_takes_effect_on_next_request(db, db_client):
    admin_c, target_c = db_client(), db_client()
    _login(db, admin_c, role="ADMIN")
    target = _login(db, target_c, role="ACCOUNTANT")

    # محاسب — لا يرى قائمة المستخدمين
    assert target_c.get("/users").status_code == 403

    admin_c.patch(f"/users/{target.id}", json={"role": "ADMIN"}, headers=_csrf(admin_c))
    # ترقية سرت فوراً على نفس الجلسة — بلا إعادة تسجيل دخول
    assert target_c.get("/users").status_code == 200

    admin_c.patch(f"/users/{target.id}", json={"role": "ACCOUNTANT"}, headers=_csrf(admin_c))
    # سحب الصلاحية سرى فوراً أيضاً
    assert target_c.get("/users").status_code == 403


def test_admin_cannot_disable_self(db, db_client):
    admin_c = db_client()
    admin = _login(db, admin_c, role="ADMIN")
    # مدير آخر موجود كي لا يكون هذا "آخر مدير" (نختبر حاجز النفس تحديداً)
    f.make_user(db, role="ADMIN")
    db.flush()

    r = admin_c.patch(f"/users/{admin.id}", json={"is_active": False}, headers=_csrf(admin_c))
    assert r.status_code == 409
    assert admin_c.get("/auth/me").status_code == 200  # لا يزال داخلاً


def test_admin_cannot_demote_self(db, db_client):
    admin_c = db_client()
    admin = _login(db, admin_c, role="ADMIN")
    f.make_user(db, role="ADMIN")
    db.flush()

    r = admin_c.patch(f"/users/{admin.id}", json={"role": "ACCOUNTANT"}, headers=_csrf(admin_c))
    assert r.status_code == 409


def test_patch_users_requires_admin_and_csrf(db, db_client):
    acc_c = db_client()
    acc = _login(db, acc_c, role="ACCOUNTANT")
    # بلا CSRF
    assert acc_c.patch(f"/users/{acc.id}", json={"is_active": False}).status_code == 403
    # محاسب بـCSRF صالح — لا يزال ممنوعاً (دور)
    assert acc_c.patch(f"/users/{acc.id}", json={"is_active": False}, headers=_csrf(acc_c)).status_code == 403


def test_patch_unknown_user_404(db, db_client):
    admin_c = db_client()
    _login(db, admin_c, role="ADMIN")
    r = admin_c.patch("/users/99999999", json={"is_active": False}, headers=_csrf(admin_c))
    assert r.status_code == 404


def test_patch_invalid_role_422(db, db_client):
    admin_c, target_c = db_client(), db_client()
    _login(db, admin_c, role="ADMIN")
    target = _login(db, target_c, role="ACCOUNTANT")
    r = admin_c.patch(f"/users/{target.id}", json={"role": "SUPERUSER"}, headers=_csrf(admin_c))
    assert r.status_code == 422
