"""لا QR مكسور ولا رابط دعوة بعنوان مؤقت (٢٠٢٦-١٠-١٢، قرار مالك): في الإنتاج بلا `PUBLIC_BASE_URL` نطاق HTTPS صالحاً
يُرفض توليد المستند/الرابط برسالة عربية (503) **قبل** أي عمل (فلا دعوة تُنشأ ولا مستند يُولَّد). محلياً يبقى الافتراضي."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import public_url
from app.config import settings
from app.database import get_db
from app.main import app
from app.models import ClientPortalInvite
from app.security.passwords import hash_password
from tests import factories as f


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def _login(db, client: TestClient, *, role: str = "ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200, resp.text
    return user


def _headers(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token, "Idempotency-Key": uuid.uuid4().hex}


# ── الوحدة: ما يُقبَل وما يُرفَض في الإنتاج ───────────────────────────────────


@pytest.mark.parametrize("value", [
    "", "   ", "http://127.0.0.1:8000", "http://localhost", "https://localhost", "https://144.91.81.150",
    "http://144.91.81.150", "http://wamda.example.com", "https://[::1]", "wamda.example.com",
    "https://wamda.example.com/app",
])
def test_production_rejects_non_https_domain(monkeypatch, value):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "public_base_url", value)
    with pytest.raises(public_url.PublicBaseUrlNotConfiguredError) as exc:
        public_url.base_url()
    assert "PUBLIC_BASE_URL" in str(exc.value)
    assert public_url.base_url_or_none() is None


@pytest.mark.parametrize("value, expected", [
    ("https://wamda.example.com", "https://wamda.example.com"),
    ("https://wamda.example.com/", "https://wamda.example.com"),
    ("https://app.wamda.example.com:8443", "https://app.wamda.example.com:8443"),
])
def test_production_accepts_https_domain(monkeypatch, value, expected):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "public_base_url", value)
    assert public_url.base_url() == expected


def test_local_keeps_default_even_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "public_base_url", "")
    assert public_url.base_url() == public_url.LOCAL_DEFAULT


# ── المسارات: رفض واضح قبل أي عمل ─────────────────────────────────────────────


def _fund(db, user, now):
    c = f.make_client(db, name="عميل حارس العنوان")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    return c, entry


def test_documents_with_qr_refused_in_production_without_domain(db, client, now, monkeypatch):
    user = _login(db, client)
    c, entry = _fund(db, user, now)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "public_base_url", "")
    for path in (
        f"/documents/receipt/{entry.id}.pdf", f"/documents/receipt/{entry.id}.png",
        f"/documents/balance-card/{c.id}.png", f"/documents/balance-card/{c.id}.pdf",
    ):
        resp = client.get(path)
        assert resp.status_code == 503, (path, resp.status_code)
        assert "PUBLIC_BASE_URL" in resp.json()["detail"], path
        assert resp.headers["content-type"].startswith("application/json"), path  # لا PDF/PNG مكسور
    # مستندات بلا QR لا تتأثر بغياب النطاق
    assert client.get("/documents/reports/trial-balance.pdf").status_code == 200


def test_invites_refused_before_any_write_in_production_without_domain(db, client, monkeypatch):
    _login(db, client)
    c = f.make_client(db, name="عميل دعوة بلا نطاق")
    before = db.execute(select(func.count()).select_from(ClientPortalInvite)).scalar()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "public_base_url", "http://144.91.81.150")
    for action in ("enable", "invite", "reset"):
        resp = client.post(f"/clients/{c.id}/portal/{action}", headers=_headers(client))
        assert resp.status_code == 503, (action, resp.status_code, resp.text)
        assert "PUBLIC_BASE_URL" in resp.json()["detail"]
    assert db.execute(select(func.count()).select_from(ClientPortalInvite)).scalar() == before
    db.refresh(c)
    assert not c.portal_enabled


def test_documents_and_invites_work_with_https_domain_and_qr_points_to_it(db, client, now, monkeypatch):
    user = _login(db, client)
    c, entry = _fund(db, user, now)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "public_base_url", "https://wamda.example.com/")

    import app.routers.documents as documents_router

    seen: list[str] = []
    real = documents_router.qr_data_uri
    monkeypatch.setattr(documents_router, "qr_data_uri", lambda data: (seen.append(data), real(data))[1])

    resp = client.get(f"/documents/receipt/{entry.id}.pdf")
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    assert seen and seen[0].startswith("https://wamda.example.com/?q="), seen
    assert "//?q=" not in seen[0]

    resp = client.post(f"/clients/{c.id}/portal/enable", headers=_headers(client))
    assert resp.status_code == 200, resp.text
    assert resp.json()["invite_url"].startswith("https://wamda.example.com/static/app/portal.html#invite=")
