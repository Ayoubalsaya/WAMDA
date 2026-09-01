"""اختبارات HTTP لبوابة العميل (`app/routers/portal.py`، §٧-٦) — تشمل
اختبارات القبول ٤٠ (عزل البوابة) · ٤١ (`cost_rate` محجوب) · ٤٢ (لا شيء
قبل تغيير كلمة المرور)."""

from __future__ import annotations

import uuid
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


def _headers(client: TestClient, idem: str | None = None) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token, "Idempotency-Key": idem or uuid.uuid4().hex}


def _make_portal_client(db, *, password: str = "PortalPass!123", must_change: bool = False):
    c = f.make_client(db)
    c.portal_password_hash = hash_password(password)
    c.portal_must_change = must_change
    c.portal_security_question = "ما اسم أول عميل؟"
    from app.security.passwords import hash_security_answer

    c.portal_security_answer_hash = hash_security_answer("تجربة")
    db.flush()
    return c


def _portal_login(client: TestClient, code: str, password: str = "PortalPass!123"):
    resp = client.post("/portal/login", json={"code": code, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _staff_login(db, client: TestClient, *, role: str = "ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200
    return user


def _find_key_anywhere(payload, key: str) -> list[str]:
    hits: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key:
                    hits.append(path + "." + k)
                walk(v, path + "." + k)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(payload, "$")
    return hits


def test_portal_login_success_uses_separate_cookie_from_staff(db, client):
    c = _make_portal_client(db)
    result = _portal_login(client, c.code)
    assert result == {"status": "ok", "must_change_password": False}
    assert client.cookies.get("wamda_portal_session")
    assert client.cookies.get("wamda_session") is None


def test_portal_login_wrong_password_rejected_and_locks_after_five(db, client):
    c = _make_portal_client(db)
    for _ in range(5):
        resp = client.post("/portal/login", json={"code": c.code, "password": "wrong"})
        assert resp.status_code == 401
    # المحاولة السادسة يجب أن تكون رفضاً بسبب القفل تحديداً (كلمة مرور صحيحة الآن مرفوضة أيضاً)
    resp = client.post("/portal/login", json={"code": c.code, "password": "PortalPass!123"})
    assert resp.status_code == 401
    assert "مقفل" in resp.json()["detail"]


def test_portal_unknown_code_rejected_generic_message(db, client):
    resp = client.post("/portal/login", json={"code": "NO-SUCH-CODE", "password": "x"})
    assert resp.status_code == 401


@pytest.mark.acceptance(42)
def test_portal_must_change_password_sees_nothing(db, client, now):
    """اختبار القبول ٤٢: عميل قبل تغيير كلمة المرور أول دخول → لا يرى شيئاً."""
    c = _make_portal_client(db, must_change=True)
    result = _portal_login(client, c.code)
    assert result["must_change_password"] is True

    # /me يبقى متاحاً عمداً (تحتاجه الواجهة لعرض شاشة تغيير كلمة المرور نفسها)
    me = client.get("/portal/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    # كل شيء آخر محجوب تماماً
    balances = client.get("/portal/balances")
    assert balances.status_code == 403
    statement = client.get("/portal/statement?currency=LYD&location=TRIPOLI")
    assert statement.status_code == 403


def test_portal_change_password_then_access_granted(db, client, now):
    c = _make_portal_client(db, must_change=True)
    _portal_login(client, c.code)
    resp = client.post(
        "/portal/change-password",
        json={"current_password": "PortalPass!123", "new_password": "BrandNewPass!456"},
        headers=_headers(client),
    )
    assert resp.status_code == 204

    balances = client.get("/portal/balances")
    assert balances.status_code == 200

    # كلمة المرور القديمة لم تعد صالحة لدخول جديد
    client2 = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[get_db] = lambda: db
    resp2 = client2.post("/portal/login", json={"code": c.code, "password": "PortalPass!123"})
    assert resp2.status_code == 401


@pytest.mark.acceptance(40)
def test_portal_isolation_no_id_param_and_staff_endpoints_reject_portal_session(db, client, now):
    """اختبار القبول ٤٠: عزل البوابة — لا مسار في البوابة يقبل معرّف عميل
    من الطلب إطلاقاً (بنيوياً لا وقت تشغيل)، ومسارات الموظف ترفض جلسة
    بوابة تماماً حتى لو استُخدمت خطأً."""
    c1 = _make_portal_client(db)
    c2 = f.make_client(db)
    f.fund_client(
        db, client=c2, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("9999.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    _portal_login(client, c1.code)

    # محاولة تسريب بيانات عميل آخر عبر أي باراميتر مُخترَع — يُتجاهَل تماماً،
    # الاستعلام دائماً على هوية الجلسة (c1) لا أي مُدخَل من الطلب
    resp = client.get(f"/portal/balances?client_id={c2.id}")
    assert resp.status_code == 200
    for row in resp.json():
        assert "9999" not in row["balance"]  # رصيد c2 لم يظهر إطلاقاً

    resp2 = client.get(f"/portal/statement?currency=LYD&location=TRIPOLI&client_id={c2.id}")
    assert resp2.status_code == 200
    assert resp2.json()["closing_balance"] != "9999.000000"

    # جلسة بوابة صالحة تُرفَض تماماً على أي مسار موظف — حتى القراءة فقط
    staff_resp = client.get(f"/clients/{c2.id}/balances")
    assert staff_resp.status_code == 401
    staff_list = client.get("/clients")
    assert staff_list.status_code == 401


@pytest.mark.acceptance(41)
def test_portal_responses_never_contain_cost_rate(db, client, now):
    """اختبار القبول ٤١: `cost_rate` غير موجود في أي رد API **للبوابة نفسها**
    (لا الموظف فقط — ذاك مُغطّى بتغطية جزئية منفصلة في test_operations_api.py).
    ينشئ العميل عملية EXCHANGE حقيقية (تستقبل cost_rate كمُدخَل) ثم يفحص كل
    رد بوابة تكرارياً."""
    c = _make_portal_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.15"), client_rate=Decimal("5.10"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
    )

    _portal_login(client, c.code)
    responses = []
    me = client.get("/portal/me")
    assert me.status_code == 200
    responses.append(("GET /portal/me", me.json()))
    balances = client.get("/portal/balances")
    assert balances.status_code == 200
    responses.append(("GET /portal/balances", balances.json()))
    statement = client.get("/portal/statement?currency=USD&location=TRIPOLI")
    assert statement.status_code == 200
    responses.append(("GET /portal/statement", statement.json()))

    leaks = {label: hits for label, body in responses if (hits := _find_key_anywhere(body, "cost_rate"))}
    assert not leaks, f"cost_rate ظهر في رد بوابة لم يُتوقَّع ظهوره فيه: {leaks}"


def test_admin_sets_portal_credentials_then_client_can_login(db, client):
    _staff_login(db, client, role="ADMIN")
    c = f.make_client(db)
    resp = client.put(
        f"/clients/{c.id}/portal-credentials",
        json={"initial_password": "FirstTimePass!789", "security_question": "س؟", "security_answer": "ج"},
        headers=_headers(client),
    )
    assert resp.status_code == 204

    client2 = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[get_db] = lambda: db
    result = client2.post("/portal/login", json={"code": c.code, "password": "FirstTimePass!789"})
    assert result.status_code == 200
    assert result.json()["must_change_password"] is True


def test_accountant_cannot_set_portal_credentials(db, client):
    _staff_login(db, client, role="ACCOUNTANT")
    c = f.make_client(db)
    resp = client.put(
        f"/clients/{c.id}/portal-credentials",
        json={"initial_password": "FirstTimePass!789"},
        headers=_headers(client),
    )
    assert resp.status_code == 403


def test_portal_recover_flow(db, client):
    c = _make_portal_client(db)
    start = client.post("/portal/recover/start", json={"code": c.code})
    assert start.status_code == 200
    assert start.json()["security_question"] == "ما اسم أول عميل؟"

    complete = client.post(
        "/portal/recover/complete",
        json={"code": c.code, "security_answer": "تجربة", "new_password": "RecoveredPass!999"},
    )
    assert complete.status_code == 204

    result = _portal_login(client, c.code, password="RecoveredPass!999")
    assert result["status"] == "ok"


def test_portal_recover_unknown_code_returns_no_question_not_error(db, client):
    resp = client.post("/portal/recover/start", json={"code": "NO-SUCH-CODE"})
    assert resp.status_code == 200
    assert resp.json()["security_question"] is None


def test_portal_write_without_csrf_rejected(db, client):
    c = _make_portal_client(db)
    _portal_login(client, c.code)
    resp = client.post(
        "/portal/change-password",
        json={"current_password": "PortalPass!123", "new_password": "AnotherPass!000"},
        headers={"Idempotency-Key": uuid.uuid4().hex},  # بلا X-CSRF-Token
    )
    assert resp.status_code == 403


def test_portal_logout_revokes_session(db, client):
    c = _make_portal_client(db)
    _portal_login(client, c.code)
    logout_resp = client.post("/portal/logout", headers=_headers(client))
    assert logout_resp.status_code == 204
    me = client.get("/portal/me")
    assert me.status_code == 401
