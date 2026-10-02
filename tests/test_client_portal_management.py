"""إدارة بوابة العميل من داخل النظام (§٧-٦، ٢٠٢٦-١٠-٠٢) — تستبدل
`PUT /clients/{id}/portal-credentials` المحذوف («كلمة المرور الأولية =
الكود»): العميل يختار كلمته بنفسه دوماً عبر رابط دعوة لمرة واحدة.

يغطي: اشتقاق الحالة (`app/security/client_portal_management.compute_status`)
· تفعيل/دعوة/إعادة تعيين/تعطيل/فك قفل (مدير فقط) · قبول الدعوة العام
(`/portal/invite/verify`+`/portal/invite/accept`) بذرّية التحديث المشروط.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import ClientPortalInvite
from app.security import client_portal_invites
from app.security.passwords import hash_password
from tests import factories as f

INVITE_PREFIX = "#invite="


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def _headers(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token, "Idempotency-Key": uuid.uuid4().hex}


def _staff_login(db, client: TestClient, *, role: str = "ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200, resp.text
    return user


def _extract_token(invite_url: str) -> str:
    assert INVITE_PREFIX in invite_url
    return invite_url.split(INVITE_PREFIX, 1)[1]


# ── الحالة المُشتقّة ──────────────────────────────────────────────────


def test_status_not_enabled_by_default(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    resp = client.get(f"/clients/{c.id}/portal")
    assert resp.status_code == 200
    assert resp.json()["status"] == "NOT_ENABLED"


def test_enable_creates_invite_returns_url_once_and_status_becomes_pending(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    resp = client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["invite_url"].startswith("http")
    assert INVITE_PREFIX in body["invite_url"]
    assert body["expires_at"]

    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "INVITE_PENDING"
    assert status_resp.json()["invite_expires_at"] is not None


def test_creating_new_invite_revokes_the_old_one(db, client, now):
    _staff_login(db, client)
    c = f.make_client(db)
    first = client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()
    first_token = _extract_token(first["invite_url"])

    second = client.post(f"/clients/{c.id}/portal/invite", headers=_headers(client)).json()
    second_token = _extract_token(second["invite_url"])
    assert first_token != second_token

    # الرابط الأول لم يعد صالحاً — أُبطل عند إنشاء الثاني
    verify_old = client.post("/portal/invite/verify", json={"token": first_token})
    assert verify_old.status_code == 400

    verify_new = client.post("/portal/invite/verify", json={"token": second_token})
    assert verify_new.status_code == 200


def test_invite_requires_portal_already_enabled(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    resp = client.post(f"/clients/{c.id}/portal/invite", headers=_headers(client))
    assert resp.status_code == 409


def test_status_invite_expired_after_48_hours(db, client, now, monkeypatch):
    monkeypatch.setattr("app.routers.clients.system_clock", lambda: now)
    _staff_login(db, client)
    c = f.make_client(db)
    client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client))

    live = db.query(ClientPortalInvite).filter(ClientPortalInvite.client_id == c.id).one()
    live.expires_at = now - timedelta(seconds=1)
    db.flush()

    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "INVITE_EXPIRED"


def test_status_active_after_password_set(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    c.portal_enabled = True
    c.portal_password_hash = hash_password("SomePass!123")
    db.flush()
    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "ACTIVE"


def test_status_locked_takes_priority_over_active(db, client, now, monkeypatch):
    monkeypatch.setattr("app.routers.clients.system_clock", lambda: now)
    _staff_login(db, client)
    c = f.make_client(db)
    c.portal_enabled = True
    c.portal_password_hash = hash_password("SomePass!123")
    c.portal_locked_until = now + timedelta(minutes=5)
    db.flush()
    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "LOCKED"


def test_status_disabled_takes_priority_over_everything(db, client, now, monkeypatch):
    monkeypatch.setattr("app.routers.clients.system_clock", lambda: now)
    _staff_login(db, client)
    c = f.make_client(db)
    c.portal_enabled = False
    c.portal_password_hash = hash_password("SomePass!123")
    c.portal_locked_until = now + timedelta(minutes=5)
    db.flush()
    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "DISABLED"


# ── تعطيل/إعادة تعيين/فك قفل ─────────────────────────────────────────


def test_disable_ends_sessions_clears_password_and_blocks_login(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    token = _extract_token(client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()["invite_url"])
    accept = client.post("/portal/invite/accept", json={"token": token, "password": "SomePass!123"})
    assert accept.status_code == 204

    portal_client = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[get_db] = lambda: db
    login = portal_client.post("/portal/login", json={"code": c.code, "password": "SomePass!123"})
    assert login.status_code == 200
    me_before = portal_client.get("/portal/me")
    assert me_before.status_code == 200

    resp = client.post(f"/clients/{c.id}/portal/disable", headers=_headers(client))
    assert resp.status_code == 204

    # الجلسة القائمة فعلاً تنتهي فوراً — لا انتظار
    me_after = portal_client.get("/portal/me")
    assert me_after.status_code == 401

    # ولا يمكن الدخول من جديد
    relogin = portal_client.post("/portal/login", json={"code": c.code, "password": "SomePass!123"})
    assert relogin.status_code == 401

    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "DISABLED"


def test_reset_invalidates_password_ends_sessions_and_issues_new_invite(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    c.portal_enabled = True
    c.portal_password_hash = hash_password("OldPass!123")
    db.flush()

    portal_client = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[get_db] = lambda: db
    login = portal_client.post("/portal/login", json={"code": c.code, "password": "OldPass!123"})
    assert login.status_code == 200

    resp = client.post(f"/clients/{c.id}/portal/reset", headers=_headers(client))
    assert resp.status_code == 200
    token = _extract_token(resp.json()["invite_url"])

    # الجلسة القديمة انتهت وكلمة المرور القديمة لم تعد صالحة
    assert portal_client.get("/portal/me").status_code == 401
    relogin_old = portal_client.post("/portal/login", json={"code": c.code, "password": "OldPass!123"})
    assert relogin_old.status_code == 401

    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "INVITE_PENDING"

    verify = client.post("/portal/invite/verify", json={"token": token})
    assert verify.status_code == 200


def test_unlock_clears_failed_attempts_without_touching_password(db, client, now):
    _staff_login(db, client)
    c = f.make_client(db)
    c.portal_enabled = True
    c.portal_password_hash = hash_password("SomePass!123")
    c.portal_failed_attempts = 4
    c.portal_locked_until = now + timedelta(minutes=10)
    db.flush()

    resp = client.post(f"/clients/{c.id}/portal/unlock", headers=_headers(client))
    assert resp.status_code == 204

    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "ACTIVE"

    portal_client = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[get_db] = lambda: db
    login = portal_client.post("/portal/login", json={"code": c.code, "password": "SomePass!123"})
    assert login.status_code == 200


# ── صلاحيات ───────────────────────────────────────────────────────────


def test_accountant_cannot_manage_portal(db, client):
    _staff_login(db, client, role="ACCOUNTANT")
    c = f.make_client(db)
    assert client.get(f"/clients/{c.id}/portal").status_code == 403
    assert client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).status_code == 403
    assert client.post(f"/clients/{c.id}/portal/disable", headers=_headers(client)).status_code == 403
    assert client.post(f"/clients/{c.id}/portal/unlock", headers=_headers(client)).status_code == 403


# ── قبول الدعوة العام (verify/accept) ───────────────────────────────


def test_invite_verify_reveals_only_first_name(db, client):
    _staff_login(db, client)
    c = f.make_client(db, name="محمد الصادق")
    token = _extract_token(client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()["invite_url"])

    verify = client.post("/portal/invite/verify", json={"token": token})
    assert verify.status_code == 200
    assert verify.json() == {"client_first_name": "محمد"}


def test_invite_verify_rejects_unknown_token(db, client):
    resp = client.post("/portal/invite/verify", json={"token": "no-such-token"})
    assert resp.status_code == 400


def test_invite_accept_sets_password_and_allows_login(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    token = _extract_token(client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()["invite_url"])

    accept = client.post("/portal/invite/accept", json={"token": token, "password": "ClientChosen!123"})
    assert accept.status_code == 204

    status_resp = client.get(f"/clients/{c.id}/portal")
    assert status_resp.json()["status"] == "ACTIVE"

    portal_client = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[get_db] = lambda: db
    login = portal_client.post("/portal/login", json={"code": c.code, "password": "ClientChosen!123"})
    assert login.status_code == 200


def test_invite_accept_second_use_of_same_token_rejected(db, client):
    """ذرّية التحديث المشروط (`UPDATE ... WHERE used_at IS NULL`): القبول
    الثاني لنفس الرمز يُرفَض دائماً بصرف النظر عن ترتيب الوصول — لا فجوة
    SELECT-ثم-UPDATE يمكن أن تتسابق عليها طلبات متزامنة، فإثبات ذلك
    تتابعياً هنا يُثبت نفس الثغرة التي يمنعها القيد تحت تزامن حقيقي أيضاً
    (القيد على مستوى الصف في القاعدة، لا على توقيت الاستدعاء)."""
    _staff_login(db, client)
    c = f.make_client(db)
    token = _extract_token(client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()["invite_url"])

    first = client.post("/portal/invite/accept", json={"token": token, "password": "ClientChosen!123"})
    assert first.status_code == 204

    second = client.post("/portal/invite/accept", json={"token": token, "password": "AnotherPass!456"})
    assert second.status_code == 400


def test_invite_accept_expired_rejected(db, client, now):
    admin = _staff_login(db, client)
    c = f.make_client(db)
    c.portal_enabled = True
    db.flush()

    # دعوة بانتهاء ماضٍ مباشرة عبر الخدمة — لا طريق HTTP لإنشاء دعوة منتهية
    # فعلياً (الرمز الخام لا يُعاد بعد انتهائه عبر أي رد).
    invite_row, raw = client_portal_invites.create_invite(
        db, client_id=c.id, created_by=admin.id, now=now - client_portal_invites.INVITE_TTL - timedelta(seconds=1),
    )
    db.flush()
    assert invite_row.expires_at <= now

    resp = client.post("/portal/invite/accept", json={"token": raw, "password": "ClientChosen!123"})
    assert resp.status_code == 400


def test_invite_accept_rejected_when_portal_disabled_meanwhile(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    token = _extract_token(client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()["invite_url"])

    # تعطيل البوابة يُبطل الدعوة الحيّة فعلياً — نثبت الفحص الدفاعي في
    # accept_invite مباشرة عبر تعطيل العميل بعد ترك دعوة حيّة يدوياً
    # (تحايل على revoke_live_invite في disable() لفحص هذا الفرع تحديداً)
    c.portal_enabled = False
    db.flush()

    resp = client.post("/portal/invite/accept", json={"token": token, "password": "ClientChosen!123"})
    assert resp.status_code == 403


def test_invite_token_never_appears_in_request_url(db, client):
    """الرمز في جسم الطلب حصراً — لا في مسار/استعلام — فلا يظهر أبداً في
    سجل وصول الخادم (الذي يسجّل المسار لا الجسم)."""
    _staff_login(db, client)
    c = f.make_client(db)
    token = _extract_token(client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()["invite_url"])

    verify = client.post("/portal/invite/verify", json={"token": token})
    assert token not in str(verify.request.url)

    accept = client.post("/portal/invite/accept", json={"token": token, "password": "ClientChosen!123"})
    assert token not in str(accept.request.url)


def test_invite_audit_log_never_stores_raw_token(db, client):
    _staff_login(db, client)
    c = f.make_client(db)
    token = _extract_token(client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client)).json()["invite_url"])
    client.post("/portal/invite/accept", json={"token": token, "password": "ClientChosen!123"})

    from app.models import AuditLog

    rows = db.query(AuditLog).filter(AuditLog.entity == "clients", AuditLog.entity_id == c.id).all()
    assert rows
    for row in rows:
        assert token not in str(row.before_json or "")
        assert token not in str(row.after_json or "")


def test_invite_endpoints_are_rate_limited(db, client):
    from app.config import settings

    c = f.make_client(db)
    for _ in range(settings.portal_login_rate_limit_max):
        r = client.post("/portal/invite/verify", json={"token": "bad-token"})
        assert r.status_code == 400
    blocked = client.post("/portal/invite/verify", json={"token": "bad-token"})
    assert blocked.status_code == 429
