"""§٩ المرحلة ١٢ — مصفوفة الصلاحيات: جدول تغطية صريح لكل مسار API.

قاعدة هذه المرحلة: **كل مسار × كل دور غير مصرّح = اختبار رفض**. مسار بلا
اختبار رفض يُعدّ ثغرة لا سهواً — `test_every_route_is_classified` يفشل
فوراً إن ظهر مسار جديد بلا تصنيف هنا.

الرفض يعني ٤٠١ (لا جلسة / جلسة مُبطَلة) أو ٤٠٣ (دور غير كافٍ) — لا ٢٠٠
ولا خطأ عمل (٤٠٤/٤٢٢). المسارات المُتحوِّلة تُرسَل بترويسة CSRF صالحة كي
يُختبَر حاجز **الدور** تحديداً لا حاجز CSRF.
"""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.security.passwords import hash_password
from tests import factories as f

# ── التصنيف الكامل ───────────────────────────────────────────────────
# القيم: PUBLIC · STAFF (أي موظف موثَّق) · POST_ENTRY (مدير+محاسب) ·
# ADMIN (مدير فقط) · PORTAL (جلسة عميل بوابة فقط)

PUBLIC = "PUBLIC"
STAFF = "STAFF"
POST_ENTRY = "POST_ENTRY"
ADMIN = "ADMIN"
PORTAL = "PORTAL"

ROUTE_AUTH: dict[str, str] = {
    # عام — لا مصادقة (مقصود)
    "GET /": PUBLIC,
    "GET /portal": PUBLIC,
    "GET /health": PUBLIC,
    "GET /openapi.json": PUBLIC,
    "GET /docs": PUBLIC,
    "GET /docs/oauth2-redirect": PUBLIC,
    "GET /redoc": PUBLIC,
    "POST /auth/login": PUBLIC,
    "POST /auth/recover/start": PUBLIC,
    "POST /auth/recover/complete": PUBLIC,
    "POST /portal/login": PUBLIC,
    "POST /portal/recover/start": PUBLIC,
    "POST /portal/recover/complete": PUBLIC,
    "POST /portal/invite/verify": PUBLIC,
    "POST /portal/invite/accept": PUBLIC,
    # موظف موثَّق (مدير أو محاسب)
    "GET /auth/me": STAFF,
    "POST /auth/logout": STAFF,
    "POST /auth/change-password": STAFF,
    "GET /dashboard/summary": STAFF,
    "GET /position/liquidity": STAFF,
    "GET /accounts/boxes": STAFF,
    "GET /accounts/correspondents": STAFF,
    "GET /accounts/banks": STAFF,
    "GET /lots": STAFF,
    "GET /lots/{lot_id}": STAFF,
    "GET /journal/entries": STAFF,
    "GET /search": STAFF,
    "GET /reference/currencies": STAFF,
    "GET /reference/locations": STAFF,
    "GET /reference/client-currency-locations": STAFF,
    "GET /reference/accounts": STAFF,
    "GET /reference/accounts/for-operation": STAFF,
    "GET /reference/swift-movements/pending": STAFF,
    "GET /reports/debts-by-currency": STAFF,
    "GET /reports/profit-by-period": STAFF,
    "GET /reports/trial-balance": STAFF,
    "GET /reports/income-statement": STAFF,
    "GET /reports/client-profitability": STAFF,
    "GET /reports/activity-by-currency": STAFF,
    "GET /reports/activity-by-month": STAFF,
    "GET /reports/correspondent-activity": STAFF,
    "GET /reports/swift-history": STAFF,
    "GET /reports/loss-making-operations": STAFF,
    "GET /reports/balance-overrides": STAFF,
    "GET /reports/emergency-entries": STAFF,
    "GET /reports/founding-reconciliation": STAFF,
    "GET /documents/receipt/{entry_id}.pdf": STAFF,
    "GET /documents/receipt/{entry_id}.png": STAFF,
    "GET /documents/statement/account/{account_code}.pdf": STAFF,  # حساب داخلي لا عميل
    "GET /documents/statement/account/{account_code}.xlsx": STAFF,
    "GET /documents/chain-summary/{chain_ref}.png": STAFF,
    "GET /documents/reports/{report_key}.xlsx": STAFF,
    "GET /documents/chain-summary/{chain_ref}.pdf": STAFF,
    "GET /documents/reports/{report_key}.pdf": STAFF,
    "GET /documents/reports/{report_key}.png": STAFF,
    "GET /partners": STAFF,
    "GET /partners/{partner_id}/accounts": STAFF,
    "GET /periods": STAFF,
    "GET /periods/founding": STAFF,
    "GET /settings/company": STAFF,
    "GET /settings/bank-accounts": STAFF,
    "GET /settings/currencies": STAFF,
    "GET /settings/locations": STAFF,
    "GET /settings/client-currency-locations": STAFF,
    # مدير + محاسب (POST_ENTRY)
    "GET /clients": POST_ENTRY,
    "GET /clients/search": POST_ENTRY,
    "GET /clients/similar": POST_ENTRY,  # CREATE_CLIENT (نفس أدوار POST_ENTRY: مدير/محاسب) — منع تكرار العميل قبل الإنشاء
    "GET /clients/{client_id}": POST_ENTRY,
    "POST /clients": POST_ENTRY,
    "PATCH /clients/{client_id}": POST_ENTRY,
    # بيانات مالية للعميل — كلها POST_ENTRY باتساق (§٩ المرحلة ١٢: هذان
    # المساران + مستندا العميل كانا `require_password_changed` فقط؛ شُدِّدا)
    "GET /clients/{client_id}/balances": POST_ENTRY,
    "GET /documents/balance-card/{client_id}.png": POST_ENTRY,
    "GET /documents/balance-card/{client_id}.pdf": POST_ENTRY,
    "GET /documents/statement/client/{client_id}.pdf": POST_ENTRY,
    "GET /documents/statement/client/{client_id}.xlsx": POST_ENTRY,
    "GET /clients/{client_id}/statement": POST_ENTRY,
    "POST /operations/receipt": POST_ENTRY,
    "POST /operations/payment": POST_ENTRY,
    "POST /operations/exchange": POST_ENTRY,
    "POST /operations/exchange/from-lot": POST_ENTRY,
    "POST /operations/exchange-chain": POST_ENTRY,
    "POST /operations/cash-transfer": POST_ENTRY,
    "POST /operations/local-move": POST_ENTRY,
    "POST /operations/remit-out": POST_ENTRY,
    "POST /operations/swift-out": POST_ENTRY,
    "POST /operations/swift-in": POST_ENTRY,
    "POST /operations/swift-return": POST_ENTRY,
    "POST /operations/expense": POST_ENTRY,
    # المرحلة ١٤ب — تعليقات على أي قيد (مدير/محاسب، مثل الإدخال العادي)
    "GET /operations/{entry_id}/comments": POST_ENTRY,
    "POST /operations/{entry_id}/comments": POST_ENTRY,
    "GET /operations/{entry_id}/history": POST_ENTRY,
    # مدير فقط
    "PATCH /clients/{client_id}/credit-allowed": ADMIN,
    "PUT /clients/{client_id}/credit-limits/{currency_code}": ADMIN,
    # §٧-٦ إدارة بوابة العميل (٢٠٢٦-١٠-٠٢) — تستبدل PUT /portal-credentials المحذوف
    "GET /clients/{client_id}/portal": ADMIN,
    "POST /clients/{client_id}/portal/enable": ADMIN,
    "POST /clients/{client_id}/portal/invite": ADMIN,
    "POST /clients/{client_id}/portal/reset": ADMIN,
    "POST /clients/{client_id}/portal/disable": ADMIN,
    "POST /clients/{client_id}/portal/unlock": ADMIN,
    "GET /users": ADMIN,
    "POST /users": ADMIN,
    "PATCH /users/{user_id}": ADMIN,
    "POST /operations/opening": ADMIN,
    "POST /operations/adjustment": ADMIN,
    # المرحلة ١٤ب — §٥ قاعدة ٢: تعديل/إلغاء قيد مُرحّل = EDIT_POSTED_ENTRY، مدير حصراً
    "POST /operations/{entry_id}/cancel": ADMIN,
    "POST /operations/{entry_id}/edit": ADMIN,
    "POST /partners": ADMIN,
    "POST /partners/{partner_id}/accounts": ADMIN,
    "GET /periods/opening-balances": ADMIN,
    "POST /periods/close": ADMIN,
    "POST /periods/reopen": ADMIN,
    "POST /periods/founding/close": ADMIN,
    "PUT /settings/company": ADMIN,
    "POST /settings/bank-accounts": ADMIN,
    "POST /settings/currencies": ADMIN,
    "PATCH /settings/currencies/{code}": ADMIN,
    "POST /settings/locations": ADMIN,
    "PATCH /settings/locations/{code}": ADMIN,
    "POST /settings/client-currency-locations": ADMIN,
    "GET /audit-log": ADMIN,
    "GET /reconciliation/statements": ADMIN,
    "POST /reconciliation/statements": ADMIN,
    "GET /reconciliation/statements/{statement_id}": ADMIN,
    "POST /reconciliation/statements/{statement_id}/auto-match": ADMIN,
    "PATCH /reconciliation/statements/{statement_id}/lines/{line_id}/match": ADMIN,
    "PATCH /reconciliation/statements/{statement_id}/lines/{line_id}/resolve": ADMIN,
    "POST /reconciliation/statements/{statement_id}/lines/{line_id}/adjust": ADMIN,
    # بوابة العميل فقط
    "GET /portal/me": PORTAL,
    "POST /portal/logout": PORTAL,
    "POST /portal/change-password": PORTAL,
    "GET /portal/currencies": PORTAL,
    "GET /portal/locations": PORTAL,
    "GET /portal/balances": PORTAL,
    "GET /portal/statement": PORTAL,
    "GET /portal/balance-card.png": PORTAL,
}

# الأدوار الممنوعة لكل تصنيف — ما يجب أن يُرفَض
DENIED_ROLES: dict[str, tuple[str, ...]] = {
    STAFF: ("anon", "portal"),
    POST_ENTRY: ("anon", "portal"),
    ADMIN: ("anon", "accountant", "portal"),
    PORTAL: ("anon", "staff_admin", "staff_accountant"),
}

# قيم عيّنة لوسائط المسار
_PARAM_SAMPLE = {
    "lot_id": "1", "entry_id": "1", "client_id": "1", "account_code": "1000",
    "chain_ref": "X", "report_key": "trial-balance", "partner_id": "1",
    "user_id": "1", "currency_code": "USD", "statement_id": "1",
    "line_id": "1", "code": "USD",
}


def _concrete(path: str) -> str:
    for name, val in _PARAM_SAMPLE.items():
        path = path.replace("{" + name + "}", val)
    return path


def _method_of(key: str) -> str:
    return key.split(" ", 1)[0]


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


def _staff_login(db, c: TestClient, role: str) -> None:
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    r = c.post("/auth/login", json={
        "username": user.username, "password": "Sup3rSecret!1",
        "totp_code": pyotp.TOTP(user.totp_secret).now(),
    })
    assert r.status_code == 200


def _portal_login(db, c: TestClient) -> None:
    client_row = f.make_client(db)
    client_row.portal_enabled = True
    client_row.portal_password_hash = hash_password("PortalPass!123")
    db.flush()
    r = c.post("/portal/login", json={"code": client_row.code, "password": "PortalPass!123"})
    assert r.status_code == 200, r.text


def _actor_client(db, make, actor: str) -> TestClient:
    c = make()
    c.get("/health")  # يضمن كوكي CSRF
    if actor == "anon":
        pass
    elif actor == "staff_admin":
        _staff_login(db, c, "ADMIN")
    elif actor in ("accountant", "staff_accountant"):
        _staff_login(db, c, "ACCOUNTANT")
    elif actor == "portal":
        _portal_login(db, c)
    return c


def _route_required_actions(path: str, method: str) -> set:
    """كل `Action` يفرضها أي `require_role` في سلسلة تبعيات المسار."""
    from app.security.permissions import Action as _A

    for r in app.routes:
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or []):
            found = set()
            stack = list(getattr(r.dependant, "dependencies", []))
            while stack:
                d = stack.pop()
                act = getattr(getattr(d, "call", None), "required_action", None)
                if isinstance(act, _A):
                    found.add(act)
                stack.extend(getattr(d, "dependencies", []))
            return found
    raise AssertionError(f"لا مسار {method} {path}")


def test_client_financial_reads_all_require_post_entry():
    """§٩ المرحلة ١٢ — بيانات العميل المالية (أرصدة · كشف · بطاقة)
    كلها خلف `POST_ENTRY` صراحةً، لا حاجز الموظف العام وحده. يمنع تكرار
    التفاوت الذي كان: `/clients/{id}/balances` ومستندَي العميل كانت
    `require_password_changed` فقط."""
    from app.security.permissions import Action as _A

    for path in (
        "/clients/{client_id}/balances",
        "/clients/{client_id}/statement",
        "/documents/balance-card/{client_id}.png",
        "/documents/balance-card/{client_id}.pdf",
        "/documents/statement/client/{client_id}.pdf",
        "/documents/statement/client/{client_id}.xlsx",
    ):
        assert _A.POST_ENTRY in _route_required_actions(path, "GET"), (
            f"{path} لا يفرض POST_ENTRY صراحةً"
        )


def test_every_route_is_classified():
    """أي مسار في التطبيق بلا تصنيف صريح هنا = ثغرة محتملة، يفشل فوراً."""
    live = set()
    for r in app.routes:
        methods = getattr(r, "methods", None) or []
        for m in methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            live.add(f"{m} {r.path}")
    classified = set(ROUTE_AUTH)
    missing = live - classified
    stale = classified - live
    assert not missing, f"مسارات بلا تصنيف صلاحيات: {sorted(missing)}"
    assert not stale, f"تصنيفات لمسارات غير موجودة: {sorted(stale)}"


@pytest.mark.parametrize(
    "route_key",
    [k for k, v in ROUTE_AUTH.items() if v != PUBLIC],
    ids=lambda k: k.replace(" ", "_"),
)
def test_unauthorized_roles_are_denied(db, client, route_key):
    kind = ROUTE_AUTH[route_key]
    method, path = route_key.split(" ", 1)
    url = _concrete(path)
    for actor in DENIED_ROLES[kind]:
        c = _actor_client(db, client, actor)
        headers = {}
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            tok = c.cookies.get("wamda_csrf")
            if tok:
                headers["X-CSRF-Token"] = tok
        resp = c.request(method, url, json={} if method != "GET" else None, headers=headers)
        assert resp.status_code in (401, 403), (
            f"{route_key} سمح لـ{actor} بالوصول (رمز {resp.status_code}) — يجب أن يُرفَض"
        )
