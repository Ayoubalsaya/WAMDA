"""اختبارات تكامل عبر HTTP فعلي (FastAPI TestClient) — الكوكي وCSRF
والجلسة تُختبَر على مستوى الطلب/الرد الحقيقي، لا استدعاء دوال مباشر.
"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.security.deps import SESSION_COOKIE_NAME
from app.security.passwords import hash_password
from tests import factories as f


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    # base_url https:// إلزامي — كوكي الجلسة/CSRF كلاهما Secure (§٩)، وhttpx
    # يرفض إعادة إرسال كوكي Secure على اتصال http عادي (سلوك سليم حسب
    # المعيار لا عيباً)؛ محاكاة HTTPS هنا مطابقة لبيئة الإنتاج الفعلية.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_staff_user(db, *, role="ADMIN", password="Sup3rSecret!1"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    db.flush()
    return user


def _csrf_headers(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token, "لا كوكي CSRF — الوسيط لم يضبطها"
    return {"X-CSRF-Token": token}


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_csrf_cookie_set_on_first_response(client):
    client.get("/health")
    assert client.cookies.get("wamda_csrf") is not None


def test_full_login_flow_first_time_totp_setup(db, client):
    user = _make_staff_user(db)

    resp1 = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1"})
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["status"] == "totp_setup_required"
    candidate_secret = body1["totp_secret"]
    assert user.username in body1["provisioning_uri"]

    valid_code = pyotp.TOTP(candidate_secret).now()
    resp2 = client.post(
        "/auth/login",
        json={
            "username": user.username, "password": "Sup3rSecret!1",
            "totp_secret_setup": candidate_secret, "totp_code": valid_code,
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "ok"
    assert resp2.json()["must_change_password"] is True
    assert client.cookies.get(SESSION_COOKIE_NAME) is not None

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == user.username


def test_wrong_password_returns_401(db, client):
    user = _make_staff_user(db)
    resp = client.post("/auth/login", json={"username": user.username, "password": "wrong"})
    assert resp.status_code == 401


def test_me_without_session_returns_401(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_logout_requires_csrf_header(db, client):
    user = _make_staff_user(db)
    user.totp_secret = pyotp.random_base32()
    db.flush()
    valid_code = pyotp.TOTP(user.totp_secret).now()
    client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": valid_code})
    assert client.cookies.get(SESSION_COOKIE_NAME) is not None

    resp_no_csrf = client.post("/auth/logout")
    assert resp_no_csrf.status_code == 403

    resp_with_csrf = client.post("/auth/logout", headers=_csrf_headers(client))
    assert resp_with_csrf.status_code == 204


def test_change_password_requires_csrf_and_current_password(db, client):
    user = _make_staff_user(db)
    user.totp_secret = pyotp.random_base32()
    db.flush()
    valid_code = pyotp.TOTP(user.totp_secret).now()
    client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": valid_code})

    # بلا CSRF
    resp_no_csrf = client.post(
        "/auth/change-password", json={"current_password": "Sup3rSecret!1", "new_password": "NewPassword!2"}
    )
    assert resp_no_csrf.status_code == 403

    # بكلمة مرور حالية خاطئة
    resp_wrong_current = client.post(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "NewPassword!2"},
        headers=_csrf_headers(client),
    )
    assert resp_wrong_current.status_code == 401

    resp_ok = client.post(
        "/auth/change-password",
        json={"current_password": "Sup3rSecret!1", "new_password": "NewPassword!2"},
        headers=_csrf_headers(client),
    )
    assert resp_ok.status_code == 204


def test_recovery_flow_via_security_question(db, client):
    from app.security.passwords import hash_security_answer

    user = _make_staff_user(db)
    user.security_question = "مدينتك المفضلة؟"
    user.security_answer_hash = hash_security_answer("طرابلس")
    db.flush()

    resp_start = client.post("/auth/recover/start", json={"username": user.username})
    assert resp_start.status_code == 200
    assert resp_start.json()["security_question"] == "مدينتك المفضلة؟"

    resp_wrong = client.post(
        "/auth/recover/complete",
        json={"username": user.username, "security_answer": "بنغازي", "new_password": "Recovered!123"},
    )
    assert resp_wrong.status_code == 401

    resp_ok = client.post(
        "/auth/recover/complete",
        json={"username": user.username, "security_answer": "طرابلس", "new_password": "Recovered!123"},
    )
    assert resp_ok.status_code == 204
