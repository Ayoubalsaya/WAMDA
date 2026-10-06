"""§٩ المرحلة ١٢ — كل مسار كتابة يتطلب CSRF فعلياً.

يُثبِت آلياً أن كل POST/PUT/PATCH/DELETE في التطبيق يرفض الطلب بلا ترويسة
`X-CSRF-Token` مطابقة للكوكي — عدا مسارات ما-قبل-الجلسة (الدخول/الاستعادة:
لا جلسة قائمة لتُحمى بعد).

الفاعل في كل حالة **دور مصرَّح له** — فرفض ٤٠٣ لا يمكن أن يأتي إلا من
حاجز CSRF، لا من حاجز الدور.
"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from tests.route_utils import all_routes
from app.security.passwords import hash_password
from tests import factories as f
from tests.test_permission_matrix import ADMIN, PORTAL, POST_ENTRY, ROUTE_AUTH, STAFF, _concrete

# مسارات ما-قبل-الجلسة — CSRF لا ينطبق (لا جلسة سابقة لحمايتها)
CSRF_EXEMPT = {
    "POST /auth/login",
    "POST /portal/login",
    "POST /portal/invite/verify",
    "POST /portal/invite/accept",
}

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture()
def client(db):
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


def _login_allowed(db, c: TestClient, kind: str) -> None:
    c.get("/health")
    if kind == PORTAL:
        cl = f.make_client(db)
        cl.portal_enabled = True
        cl.portal_password_hash = hash_password("PortalPass!123")
        db.flush()
        r = c.post("/portal/login", json={"code": cl.code, "password": "PortalPass!123"})
        assert r.status_code == 200
        return
    role = "ADMIN" if kind == ADMIN else "ACCOUNTANT"  # STAFF/POST_ENTRY: محاسب يكفي
    u = f.make_user(db, role=role)
    u.password_hash = hash_password("Sup3rSecret!1")
    u.must_change_password = False
    u.totp_secret = pyotp.random_base32()
    db.flush()
    r = c.post("/auth/login", json={
        "username": u.username, "password": "Sup3rSecret!1", "totp_code": pyotp.TOTP(u.totp_secret).now(),
    })
    assert r.status_code == 200


_MUTATING_ROUTES = [
    k for k, v in ROUTE_AUTH.items()
    if k.split(" ", 1)[0] in _MUTATING and k not in CSRF_EXEMPT
]


def test_all_mutating_routes_are_covered():
    """كل مسار كتابة إمّا مُعفى صراحةً أو مُختبَر — لا ثالث."""
    live_mutating = set()
    for r in all_routes(app):
        for m in getattr(r, "methods", None) or []:
            if m in _MUTATING:
                live_mutating.add(f"{m} {r.path}")
    covered = set(_MUTATING_ROUTES) | CSRF_EXEMPT
    assert live_mutating - covered == set(), f"مسارات كتابة بلا تغطية CSRF: {live_mutating - covered}"


@pytest.mark.parametrize("route_key", _MUTATING_ROUTES, ids=lambda k: k.replace(" ", "_"))
def test_mutating_route_rejects_without_csrf_header(db, client, route_key):
    kind = ROUTE_AUTH[route_key]
    method, path = route_key.split(" ", 1)
    c = client()
    _login_allowed(db, c, kind)
    # لا ترويسة X-CSRF-Token — الكوكي وحده لا يكفي (double-submit)
    resp = c.request(method, _concrete(path), json={})
    assert resp.status_code == 403, (
        f"{route_key} قُبِل بلا ترويسة CSRF (رمز {resp.status_code}) — حاجز CSRF مفقود"
    )
