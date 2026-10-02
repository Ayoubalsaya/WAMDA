"""بحث العملاء المُطبَّع + منع التكرار + صلاحية إنشاء العميل (٢٠٢٦-١٠-٠٢، الإضافة السريعة من دفتر اليومية).

السبب الأول لتكرار العملاء بحث لا يجد الموجود: `/clients/search` كان يطابق `name_ar` الخام، فـ«احمد» لا تجد «أحمد».
الآن يطابق `search_name` المُطبَّع بنفس دالة القاعدة (`fn_normalize_arabic`)."""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models import AuditLog, Client
from app.security import permissions
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


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf")}


def _mk(db, name, phone=None):
    c = Client(code=f"T-{f.uid()}", name_ar=name, search_name=name, phone=phone)
    db.add(c)
    db.flush()
    db.refresh(c)  # search_name يملؤه المشغّل
    return c


def _search(client, q):
    resp = client.get("/clients/search", params={"q": q})
    assert resp.status_code == 200, resp.text
    return {r["id"] for r in resp.json()}


# ═══ البحث المُطبَّع ═══


@pytest.mark.parametrize(
    "stored, query",
    [
        ("أحمد الورفلي", "احمد"),                 # أ ← ا (الحالة المُبلَغ عنها)
        ("إبراهيم السنوسي", "ابراهيم"),            # إ ← ا
        ("آمنة بن عمر", "امنه"),                   # آ ← ا و ة ← ه معاً
        ("مدرسة النور", "مدرسه"),                  # ة ← ه
        ("مصطفى المبروك", "مصطفي"),               # ى ← ي
        ("خالد الورفلّي", "الورفلي"),              # تشكيل (شدّة) في المخزَّن
        ("مُحَمَّد جابر", "محمد"),                  # تشكيل كامل
        ("عبـــدالله", "عبدالله"),                  # تطويل
        ("نادية   الصيد", "نادية الصيد"),          # مسافات داخلية متعددة
        ("فاطمة المبروك", "  فاطمة   المبروك  "),  # مسافات طرفية وداخلية في الاستعلام
    ],
)
def test_search_unifies_arabic_spelling(db, client, stored, query):
    _login(db, client)
    target = _mk(db, stored)
    assert target.id in _search(client, query)


def test_search_still_matches_code_phone_and_exact_name(db, client):
    _login(db, client)
    c = _mk(db, "سلمى بن عمر", phone="+218911112222")
    assert c.id in _search(client, c.code)
    assert c.id in _search(client, "911112222")
    assert c.id in _search(client, "سلمى بن عمر")
    assert c.id not in _search(client, "ليس موجوداً أبداً")


def test_global_search_also_normalizes(db, client):
    from decimal import Decimal

    user = _login(db, client)
    c = _mk(db, "أيمن الشاذلي")
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10.000"),
                  receiving_account_code="1101", user=user, now=__import__("datetime").datetime(2026, 6, 15, 10, tzinfo=__import__("datetime").timezone.utc))
    resp = client.get("/search", params={"q": "ايمن"})
    assert resp.status_code == 200 and len(resp.json()) >= 1


# ═══ التشابه (منع التكرار) ═══


def _similar(client, name, phone=None):
    params = {"name": name, **({"phone": phone} if phone else {})}
    resp = client.get("/clients/similar", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_similar_matches_normalized_and_reordered_names(db, client):
    _login(db, client)
    existing = _mk(db, "أحمد المبروك")
    for variant in ("احمد المبروك", "احمد   المبروك ", "المبروك أحمد", "أَحْمَد المبروك"):
        rows = _similar(client, variant)
        hit = next((r for r in rows if r["id"] == existing.id), None)
        assert hit is not None and hit["reason"] == "اسم مطابق", (variant, rows)


def test_similar_flags_close_but_not_identical_names(db, client):
    _login(db, client)
    existing = _mk(db, "محمد المنصوري")
    rows = _similar(client, "محمد المنصورى")  # ى بدل ي → مطابق بعد التوحيد
    assert any(r["id"] == existing.id for r in rows)
    rows = _similar(client, "محمد المنصوره")  # حرف مختلف قريب → مشابه
    hit = next((r for r in rows if r["id"] == existing.id), None)
    assert hit is not None and hit["reason"] in ("اسم مشابه", "اسم مطابق")


def test_similar_does_not_flag_unrelated_names(db, client):
    _login(db, client)
    _mk(db, "خالد الورفلي")
    assert not any(r["name_ar"] == "خالد الورفلي" for r in _similar(client, "سلمى بن عمر"))


def test_similar_matches_phone_regardless_of_formatting(db, client):
    _login(db, client)
    existing = _mk(db, "اسم مختلف تماماً", phone="+218 91-234-5678")
    rows = _similar(client, "عميل جديد كلياً", phone="0912345678")
    hit = next((r for r in rows if r["id"] == existing.id), None)
    assert hit is not None and hit["reason"] == "نفس الهاتف"


# ═══ الصلاحية والتدقيق ═══


def test_create_client_requires_create_client_permission_and_is_audited(db, client, monkeypatch):
    admin = _login(db, client)
    assert "CREATE_CLIENT" in client.get("/auth/me").json()["permissions"]
    resp = client.post("/clients", json={"code": f"T-{f.uid()}", "name_ar": "عميل مُدقَّق"}, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    row = db.execute(select(AuditLog).where(AuditLog.action == "CLIENT_CREATED", AuditLog.entity_id == resp.json()["id"])).scalar_one()
    assert row.actor_id == admin.id

    # دور بلا الصلاحية: ٤٠٣ من الخادم، ولا ترد الصلاحية في /auth/me (الواجهة تخفي الزر)
    monkeypatch.setitem(permissions.PERMISSION_MATRIX, permissions.Action.CREATE_CLIENT, frozenset({permissions.ADMIN}))
    client.cookies.clear()
    _login(db, client, role="ACCOUNTANT")
    assert "CREATE_CLIENT" not in client.get("/auth/me").json()["permissions"]
    resp = client.post("/clients", json={"code": f"T-{f.uid()}", "name_ar": "ممنوع"}, headers=_csrf(client))
    assert resp.status_code == 403
    assert client.get("/clients/similar", params={"name": "ممنوع"}).status_code == 403
