"""اختبارات HTTP لإدارة العملات والمواقع من شاشة الإعدادات
(`app/routers/settings.py`، ٢٠٢٦-٠٩-٢٥) — جدول · إضافة · تعديل محدود ·
تعطيل لا حذف، وإنشاء شجرة الحسابات الفرعية آلياً عند إضافة عملة."""

from __future__ import annotations

from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.engine import accounts_repo
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


# ═══ العملات ═══════════════════════════════════════════════════════════


def test_accountant_can_read_but_not_write_currencies(db, client):
    _login(db, client, role="ACCOUNTANT")
    listing = client.get("/settings/currencies")
    assert listing.status_code == 200
    create = client.post(
        "/settings/currencies", json={"code": f"T{f.uid()[:4]}", "name_ar": "عملة", "symbol": "x"},
        headers=_headers(client),
    )
    assert create.status_code == 403


def test_create_currency_builds_chart_of_accounts_and_rejects_duplicate(db, client):
    _login(db, client, role="ADMIN")
    code = f"T{f.uid()[:4]}".upper()
    resp = client.post(
        "/settings/currencies",
        json={"code": code, "name_ar": "عملة اختبار", "symbol": "T$", "decimals": 3, "sort_order": 99},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == {
        "code": code, "name_ar": "عملة اختبار", "symbol": "T$", "decimals": 3,
        "is_pivot": False, "is_active": True, "sort_order": 99,
    }

    # كل الحسابات الفرعية الاثنا عشر أُنشئت فعلاً — دون هذا يفشل أول
    # قبض/صرافة بالعملة الجديدة بحساب ربح/تصفية مفقود.
    for parent_code in accounts_repo.CURRENCY_SUBDIVIDED_PARENTS:
        sub = accounts_repo.get_currency_subaccount(db, parent_code, code)
        assert sub.currency_code == code
        assert sub.parent_id is not None

    dup = client.post(
        "/settings/currencies", json={"code": code, "name_ar": "تكرار", "symbol": "x"}, headers=_headers(client),
    )
    assert dup.status_code == 409

    listing = client.get("/settings/currencies")
    assert any(c["code"] == code for c in listing.json())


def test_update_currency_name_symbol_sort_order(db, client):
    _login(db, client, role="ADMIN")
    code = f"T{f.uid()[:4]}".upper()
    client.post("/settings/currencies", json={"code": code, "name_ar": "قبل", "symbol": "a"}, headers=_headers(client))

    resp = client.patch(
        f"/settings/currencies/{code}", json={"name_ar": "بعد", "symbol": "b", "sort_order": 5},
        headers=_headers(client),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name_ar"] == "بعد"
    assert body["symbol"] == "b"
    assert body["sort_order"] == 5


def test_currency_decimals_locked_after_first_use(db, client, now):
    from app.engine.operations import opening_balance as opening_op
    from app.models.enums import ConfidenceLevel, OpeningSourceType

    admin = _login(db, client, role="ADMIN")
    code = f"T{f.uid()[:4]}".upper()
    client.post(
        "/settings/currencies", json={"code": code, "name_ar": "عملة", "symbol": "x", "decimals": 2},
        headers=_headers(client),
    )

    # لا استخدام بعد — تعديل المنازل العشرية مسموح
    still_free = client.patch(f"/settings/currencies/{code}", json={"decimals": 4}, headers=_headers(client))
    assert still_free.status_code == 200
    assert still_free.json()["decimals"] == 4

    box = f.make_bank_account(db, currency_code=code, location_code="TRIPOLI", parent_code="1100")
    opening_op.execute(
        db, account_code=box.code, currency_code=code, amount=Decimal("100.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.LOW,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )

    locked = client.patch(f"/settings/currencies/{code}", json={"decimals": 2}, headers=_headers(client))
    assert locked.status_code == 409

    # لكن تعديل حقول أخرى (لا تمسّ التقريب) يبقى مسموحاً رغم الاستخدام
    still_ok = client.patch(f"/settings/currencies/{code}", json={"name_ar": "اسم جديد"}, headers=_headers(client))
    assert still_ok.status_code == 200
    assert still_ok.json()["name_ar"] == "اسم جديد"


def test_disable_currency_rejected_with_nonzero_balance_allowed_when_zero(db, client, now):
    from app.engine.operations import opening_balance as opening_op
    from app.models.enums import ConfidenceLevel, OpeningSourceType

    admin = _login(db, client, role="ADMIN")

    # عملة بلا استخدام إطلاقاً — التعطيل يُقبل
    idle_code = f"T{f.uid()[:4]}".upper()
    client.post("/settings/currencies", json={"code": idle_code, "name_ar": "عملة خاملة", "symbol": "x"}, headers=_headers(client))
    disable_idle = client.patch(f"/settings/currencies/{idle_code}", json={"is_active": False}, headers=_headers(client))
    assert disable_idle.status_code == 200
    assert disable_idle.json()["is_active"] is False

    # إعادة تفعيلها تعمل أيضاً
    reenable = client.patch(f"/settings/currencies/{idle_code}", json={"is_active": True}, headers=_headers(client))
    assert reenable.status_code == 200
    assert reenable.json()["is_active"] is True

    # عملة برصيد غير صفري — التعطيل يُرفَض
    funded_code = f"T{f.uid()[:4]}".upper()
    client.post("/settings/currencies", json={"code": funded_code, "name_ar": "عملة ممولة", "symbol": "x"}, headers=_headers(client))
    box = f.make_bank_account(db, currency_code=funded_code, location_code="TRIPOLI", parent_code="1100")
    opening_op.execute(
        db, account_code=box.code, currency_code=funded_code, amount=Decimal("50.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.LOW,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )

    disable_funded = client.patch(f"/settings/currencies/{funded_code}", json={"is_active": False}, headers=_headers(client))
    assert disable_funded.status_code == 409


def test_update_currency_unknown_code_404(db, client):
    _login(db, client, role="ADMIN")
    resp = client.patch("/settings/currencies/ZZZZ", json={"name_ar": "x"}, headers=_headers(client))
    assert resp.status_code == 404


# ═══ المواقع ════════════════════════════════════════════════════════════


def test_accountant_can_read_but_not_write_locations(db, client):
    _login(db, client, role="ACCOUNTANT")
    listing = client.get("/settings/locations")
    assert listing.status_code == 200
    create = client.post(
        "/settings/locations", json={"code": f"T-{f.uid()}", "name_ar": "موقع", "country": "XX"},
        headers=_headers(client),
    )
    assert create.status_code == 403


def test_create_location_and_reject_duplicate(db, client):
    _login(db, client, role="ADMIN")
    code = f"T-{f.uid()}".upper()
    resp = client.post(
        "/settings/locations", json={"code": code, "name_ar": "موقع اختبار", "country": "LY"}, headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"code": code, "name_ar": "موقع اختبار", "country": "LY", "is_active": True}

    dup = client.post(
        "/settings/locations", json={"code": code, "name_ar": "تكرار", "country": "LY"}, headers=_headers(client),
    )
    assert dup.status_code == 409


def test_update_location_name_and_country(db, client):
    _login(db, client, role="ADMIN")
    code = f"T-{f.uid()}".upper()
    client.post("/settings/locations", json={"code": code, "name_ar": "قبل", "country": "LY"}, headers=_headers(client))

    resp = client.patch(f"/settings/locations/{code}", json={"name_ar": "بعد", "country": "TR"}, headers=_headers(client))
    assert resp.status_code == 200, resp.text
    assert resp.json()["name_ar"] == "بعد"
    assert resp.json()["country"] == "TR"


def test_disable_location_rejected_with_nonzero_balance_allowed_when_zero(db, client, now):
    from app.engine.operations import opening_balance as opening_op
    from app.models.enums import ConfidenceLevel, OpeningSourceType

    admin = _login(db, client, role="ADMIN")

    idle_code = f"T-{f.uid()}".upper()
    client.post("/settings/locations", json={"code": idle_code, "name_ar": "موقع خامل", "country": "LY"}, headers=_headers(client))
    disable_idle = client.patch(f"/settings/locations/{idle_code}", json={"is_active": False}, headers=_headers(client))
    assert disable_idle.status_code == 200
    assert disable_idle.json()["is_active"] is False

    funded_code = f"T-{f.uid()}".upper()
    client.post("/settings/locations", json={"code": funded_code, "name_ar": "موقع ممول", "country": "LY"}, headers=_headers(client))
    box = f.make_bank_account(db, currency_code="LYD", location_code=funded_code, parent_code="1100")
    opening_op.execute(
        db, account_code=box.code, currency_code="LYD", amount=Decimal("50.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.LOW,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )

    disable_funded = client.patch(f"/settings/locations/{funded_code}", json={"is_active": False}, headers=_headers(client))
    assert disable_funded.status_code == 409


def test_update_location_unknown_code_404(db, client):
    _login(db, client, role="ADMIN")
    resp = client.patch("/settings/locations/ZZZZ", json={"name_ar": "x"}, headers=_headers(client))
    assert resp.status_code == 404
